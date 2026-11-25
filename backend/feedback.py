"""Feedback report: one Claude request per session, plus stats computed locally.

Claude scores the answers and writes the coaching (JSON). The numbers that can
be counted exactly (filler words, answer length, overall score) are computed
here so they are consistent from one session to the next.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from . import claude_json, db
from .categories import CATEGORIES, clean_competency, resolve_category

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


FIX_STATUSES = ("improved", "partly", "not_yet", "not_tested")


def previous_fixes_text(fixes: list[str] | None) -> str:
    if not fixes:
        return "none"
    return "\n".join(f"{i}. {f}" for i, f in enumerate(fixes, 1))


def _system_prompt(pack: dict, previous_fixes: list[str] | None = None) -> str:
    opts = pack.get("options") or {}
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "type": opts.get("interview_type") or "mixed",
        "difficulty": opts.get("difficulty") or "medium",
        "jd": pack.get("jd") or "(not provided)",
        "profile": pack.get("profile") or "(not provided)",
        "company_notes": pack.get("company_notes") or "(not provided)",
        "previous_fixes": previous_fixes_text(previous_fixes),
    }
    text = (PROMPTS_DIR / "feedback.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text



_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "question_turn": {"type": "integer"},
        "question": {"type": "string"},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "competency": {"type": "string"},
        "answer_summary": {"type": "string"},
        "scores": {
            "type": "object",
            "properties": {c: {"type": "integer", "minimum": 1, "maximum": 5} for c in CRITERIA},
            "required": list(CRITERIA),
        },
        "better_answer": {"type": "string"},
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question_turn", "question", "answer_summary", "scores", "better_answer", "tips"],
}
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "answers": {"type": "array", "items": _ANSWER_SCHEMA},
        "top_fixes": {"type": "array", "items": {"type": "string"}},
        "previous_fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fix": {"type": "string"},
                    "status": {"type": "string", "enum": list(FIX_STATUSES)},
                    "evidence": {"type": "string"},
                },
                "required": ["fix", "status"],
            },
        },
    },
    "required": ["summary", "answers", "top_fixes"],
}


async def _ask_claude(system_prompt: str, transcript: str) -> dict:
    model = os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None
    prompt = f"Transcript:\n\n{transcript}\n\nReturn the feedback JSON now."
    try:
        return await claude_json.ask_json(system_prompt, prompt, REPORT_SCHEMA, model)
    except claude_json.ClaudeJSONError as exc:
        raise FeedbackError(str(exc)) from exc


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
        question = str(a.get("question") or "")
        answers.append({
            "question_turn": qt if isinstance(qt, int) else None,
            "question": question,
            "category": resolve_category(a.get("category"), question),
            "competency": clean_competency(a.get("competency")),
            "answer_summary": str(a.get("answer_summary") or ""),
            "scores": scores,
            "average": round(sum(scores.values()) / len(CRITERIA), 1),
            "better_answer": str(a.get("better_answer") or ""),
            "tips": [str(t) for t in (a.get("tips") or []) if t][:4],
        })
    if not answers:
        raise FeedbackError("The report had no scored answers")
    fixes = [str(f) for f in (raw.get("top_fixes") or []) if f][:3]
    previous = []
    for p in raw.get("previous_fixes") or []:
        if not isinstance(p, dict) or not p.get("fix"):
            continue
        status = str(p.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
        previous.append({
            "fix": str(p["fix"]),
            "status": status if status in FIX_STATUSES else "not_tested",
            "evidence": str(p.get("evidence") or ""),
        })
    candidate_texts = [t["text"] for t in turns if t["speaker"] == "candidate"]
    return {
        # Mean of the per-answer averages: comparable across sessions.
        "overall_score": round(sum(a["average"] for a in answers) / len(answers), 1),
        "summary": str(raw.get("summary") or ""),
        "answers": answers,
        "filler_words": filler_words(candidate_texts),
        "avg_answer_seconds": answer_seconds(turns),
        "top_fixes": fixes,
        "previous_fixes": previous[:3],
    }


_FIX_MARKS = {"improved": "✓ Improved", "partly": "~ Partly", "not_yet": "✗ Not yet", "not_tested": "– Not tested"}


def _since_last_time_md(report: dict) -> list[str]:
    prev = report.get("previous_fixes") or []
    if not prev:
        return []
    out = ["## Since last time", ""]
    for p in prev:
        out.append(f"- **{_FIX_MARKS.get(p['status'], p['status'])}:** {p['fix']}" + (f" ({p['evidence']})" if p.get("evidence") else ""))
    return [*out, ""]


def to_markdown(report: dict, pack: dict, session: dict, turns: list[dict] | None = None) -> str:
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
        *_since_last_time_md(report),
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
    if turns:
        name = (pack.get("options") or {}).get("interviewer_name") or "Interviewer"
        out += ["## Transcript", ""]
        for t in turns:
            stamp = ""
            if t.get("t_start_ms") is not None:
                secs = t["t_start_ms"] // 1000
                stamp = f"`{secs // 60}:{secs % 60:02d}` "
            who = name if t["speaker"] == "interviewer" else "You"
            out += [f"{stamp}**{who}:** {t['text']}", ""]
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
        earlier = db.pack_report_history(session["pack_id"], limit=1, before=session["started_at"])
        fixes = earlier[0]["top_fixes"] if earlier else []
        raw = await _ask_claude(_system_prompt(pack, fixes), _transcript(turns))
        report = normalise(raw, turns)
        db.save_report(session_id, report, to_markdown(report, pack, session, turns))
        db.set_overall_score(session_id, report["overall_score"])
        log.info("Report ready for %s (overall %.1f)", session_id, report["overall_score"])
    except Exception as exc:
        msg = str(exc) if isinstance(exc, FeedbackError) else f"{type(exc).__name__}: {exc}"
        log.warning("Report failed for %s: %s", session_id, msg)
        db.set_report_error(session_id, msg)
