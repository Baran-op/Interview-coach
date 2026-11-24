"""Feedback report: one Claude request per session, plus stats computed locally.

Claude scores the answers and writes the coaching (JSON). The numbers that can
be counted exactly (filler words, answer length, overall score) are computed
here so they are consistent from one session to the next.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from . import db

log = logging.getLogger("interview-coach.feedback")
PROMPTS_DIR = Path(__file__).parent / "prompts"
CRITERIA = ("relevance", "structure", "specificity", "evidence")


class FeedbackError(RuntimeError):
    pass


# ------------------------------------------------------------ local stats --- #

# "like" only counts as a filler when set off by commas ("so, like, we..."),
# otherwise "I'd like to" or "tools like Jira" would be counted.
_FILLER_RE = re.compile(
    r"\b(u+m+|u+h+|e+r+m+|hmm+|you know|i mean|kind of|sort of|basically|literally|actually)\b|,\s*like\s*,",
    re.IGNORECASE,
)


def filler_words(answers: list[str]) -> dict:
    count = 0
    by_word: dict[str, int] = {}
    examples: list[str] = []
    for text in answers:
        covered = -1  # end of the last example taken from this answer
        for m in _FILLER_RE.finditer(text):
            word = (m.group(1) or "like").lower()
            word = re.sub(r"(.)\1+", r"\1", word) if word[0] in "uehm" and " " not in word else word
            count += 1
            by_word[word] = by_word.get(word, 0) + 1
            if len(examples) < 5 and m.start() >= covered:
                a, b = max(0, m.start() - 30), min(len(text), m.end() + 30)
                examples.append(("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else ""))
                covered = b
    top = sorted(by_word.items(), key=lambda kv: -kv[1])
    return {"count": count, "examples": examples, "by_word": dict(top)}


def answer_seconds(turns: list[dict]) -> float | None:
    """Average length of my answers, from recorded timings or ~150 words/min."""
    lengths = []
    for t in turns:
        if t["speaker"] != "candidate":
            continue
        if t.get("t_start_ms") is not None and t.get("t_end_ms") is not None and t["t_end_ms"] > t["t_start_ms"]:
            lengths.append((t["t_end_ms"] - t["t_start_ms"]) / 1000)
        else:
            lengths.append(len(t["text"].split()) / 2.5)
    return round(sum(lengths) / len(lengths), 1) if lengths else None


# ------------------------------------------------------------- the request --- #

def _transcript(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        who = "Interviewer" if t["speaker"] == "interviewer" else "Candidate"
        secs = ""
        if t["speaker"] == "candidate" and t.get("t_start_ms") is not None and t.get("t_end_ms") is not None:
            secs = f", {round((t['t_end_ms'] - t['t_start_ms']) / 1000)} s"
        lines.append(f"[#{t['idx']} {who}{secs}] {t['text']}")
    return "\n".join(lines)


def _system_prompt(pack: dict) -> str:
    opts = pack.get("options") or {}
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "type": opts.get("interview_type") or "mixed",
        "difficulty": opts.get("difficulty") or "medium",
        "jd": pack.get("jd") or "(not provided)",
        "profile": pack.get("profile") or "(not provided)",
    }
    text = (PROMPTS_DIR / "feedback.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise FeedbackError("Claude did not return JSON")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise FeedbackError(f"Claude returned invalid JSON: {exc}") from exc


async def _ask_claude(system_prompt: str, transcript: str) -> dict:
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        tools=[],
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],
        model=os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None,
    )
    prompt = f"Transcript:\n\n{transcript}\n\nReturn the feedback JSON now."
    parts: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            if msg.error:
                raise FeedbackError(f"Claude error: {msg.error}")
            parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage) and msg.is_error:
            raise FeedbackError(f"Claude returned an error ({msg.result or msg.subtype})")
    return _extract_json("".join(parts))


# ------------------------------------------------------------ normalising --- #

def _score(v) -> int:
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 1


def normalise(raw: dict, turns: list[dict]) -> dict:
    """Coerce Claude's JSON into the report schema and add the local stats."""
    answers = []
    for a in raw.get("answers") or []:
        if not isinstance(a, dict):
            continue
        scores = {c: _score((a.get("scores") or {}).get(c)) for c in CRITERIA}
        qt = a.get("question_turn")
        answers.append({
            "question_turn": qt if isinstance(qt, int) else None,
            "question": str(a.get("question") or ""),
            "answer_summary": str(a.get("answer_summary") or ""),
            "scores": scores,
            "average": round(sum(scores.values()) / len(CRITERIA), 1),
            "better_answer": str(a.get("better_answer") or ""),
            "tips": [str(t) for t in (a.get("tips") or []) if t][:4],
        })
    if not answers:
        raise FeedbackError("The report had no scored answers")
    fixes = [str(f) for f in (raw.get("top_fixes") or []) if f][:3]
    candidate_texts = [t["text"] for t in turns if t["speaker"] == "candidate"]
    return {
        # Mean of the per-answer averages: comparable across sessions.
        "overall_score": round(sum(a["average"] for a in answers) / len(answers), 1),
        "summary": str(raw.get("summary") or ""),
        "answers": answers,
        "filler_words": filler_words(candidate_texts),
        "avg_answer_seconds": answer_seconds(turns),
        "top_fixes": fixes,
    }


def to_markdown(report: dict, pack: dict, session: dict) -> str:
    from datetime import datetime

    when = datetime.fromtimestamp(session["started_at"] / 1000).strftime("%Y-%m-%d %H:%M")
    title = pack.get("title") or "Interview"
    out = [
        f"# Interview feedback: {title}",
        "",
        f"*{when}*" + (f" · {pack.get('role')}" if pack.get("role") else "") + (f" at {pack.get('company')}" if pack.get("company") else ""),
        "",
        f"**Overall score: {report['overall_score']} / 5** (average of the answer scores)",
        "",
        report["summary"],
        "",
        "## Top 3 things to fix",
        "",
        *[f"{i}. {f}" for i, f in enumerate(report["top_fixes"], 1)],
        "",
        "## Delivery",
        "",
        f"- Filler words: {report['filler_words']['count']}"
        + (" (" + ", ".join(f"{w} ×{n}" for w, n in report["filler_words"].get("by_word", {}).items()) + ")" if report["filler_words"]["count"] else ""),
    ]
    for ex in report["filler_words"].get("examples", []):
        out.append(f"  - \"{ex}\"")
    if report.get("avg_answer_seconds") is not None:
        out.append(f"- Average answer length: {report['avg_answer_seconds']} s")
    out += ["", "## Answers", ""]
    for i, a in enumerate(report["answers"], 1):
        s = a["scores"]
        out += [
            f"### {i}. {a['question']}",
            "",
            f"Relevance {s['relevance']}/5 · Structure {s['structure']}/5 · "
            f"Specificity {s['specificity']}/5 · Evidence {s['evidence']}/5 (average {a['average']})",
            "",
            f"**What you said:** {a['answer_summary']}",
            "",
            *[f"- {t}" for t in a["tips"]],
            "",
            "**A stronger answer:**",
            "",
            *[f"> {line}" if line else ">" for line in a["better_answer"].splitlines()],
            "",
        ]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- entry --- #

async def generate(session_id: str) -> None:
    """Build and store the report for a session. Errors are stored, not raised."""
    try:
        session = db.get_session(session_id)
        if not session:
            raise FeedbackError("Session not found")
        pack = db.get_pack(session["pack_id"]) or {}
        turns = db.list_turns(session_id)
        if not any(t["speaker"] == "candidate" for t in turns):
            raise FeedbackError("There are no answers to score: the interview ended before you answered.")
        raw = await _ask_claude(_system_prompt(pack), _transcript(turns))
        report = normalise(raw, turns)
        db.save_report(session_id, report, to_markdown(report, pack, session))
        db.set_overall_score(session_id, report["overall_score"])
        log.info("Report ready for %s (overall %.1f)", session_id, report["overall_score"])
    except Exception as exc:
        msg = str(exc) if isinstance(exc, FeedbackError) else f"{type(exc).__name__}: {exc}"
        log.warning("Report failed for %s: %s", session_id, msg)
        db.set_report_error(session_id, msg)
