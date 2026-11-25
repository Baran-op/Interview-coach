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

from . import brief as brief_mod
from . import claude_json, db, materials
from .categories import clean_competency, resolve_category

log = logging.getLogger("interview-coach.feedback")
PROMPTS_DIR = Path(__file__).parent / "prompts"
CRITERIA = ("relevance", "structure", "specificity", "evidence")  # the default brief's; a session's come from its brief


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
        if t.get("station"):
            secs += f", station {t['station']}"
        lines.append(f"[#{t['idx']} {who}{secs}] {t['text']}")
    return "\n".join(lines)


FIX_STATUSES = ("improved", "partly", "not_yet", "not_tested")


def previous_fixes_text(fixes: list[str] | None) -> str:
    if not fixes:
        return "none"
    return "\n".join(f"{i}. {f}" for i, f in enumerate(fixes, 1))


def _system_prompt(pack: dict, previous_fixes: list[str] | None = None, brief: dict | None = None) -> str:
    """The report prompt. `brief` is the session's brief snapshot; None is the default brief, which
    renders today's prompt exactly (raw JD / CV / notes and the standard rubric)."""
    opts = pack.get("options") or {}
    context = (brief_mod.legacy_context(materials.legacy_slots(pack)) if brief is None
               else brief_mod.scoring_context(brief))
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "type": opts.get("interview_type") or "mixed",
        "stage": opts.get("stage") or "full",
        "difficulty": opts.get("difficulty") or "medium",
        "context": context,
        "previous_fixes": previous_fixes_text(previous_fixes),
        **brief_mod.scoring_values(brief),
    }
    text = (PROMPTS_DIR / "feedback.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text



def report_schema(brief: dict | None = None) -> dict:
    """The report's JSON schema for a brief's criteria and categories (None: the default brief, today's schema)."""
    criteria, categories = brief_mod.criteria_keys(brief), brief_mod.category_keys(brief)
    answer = {
        "type": "object",
        "properties": {
            "question_turn": {"type": "integer"},
            "question": {"type": "string"},
            "category": {"type": "string", "enum": categories},
            "competency": {"type": "string"},
            "answer_summary": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {c: {"type": "integer", "minimum": 1, "maximum": 5} for c in criteria},
                "required": criteria,
            },
            "better_answer": {"type": "string"},
            "tips": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question_turn", "question", "answer_summary", "scores", "better_answer", "tips"],
    }
    if brief and brief["format"]["kind"] == "stations":
        answer["properties"]["station"] = {"type": "string", "enum": [st["key"] for st in brief["format"]["stations"]]}
    return _report_schema(answer)


def _report_schema(answer: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "answers": {"type": "array", "items": answer},
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


REPORT_SCHEMA = report_schema(None)


async def _ask_claude(system_prompt: str, transcript: str, schema: dict | None = None) -> dict:
    model = os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None
    prompt = f"Transcript:\n\n{transcript}\n\nReturn the feedback JSON now."
    try:
        return await claude_json.ask_json(system_prompt, prompt, schema or REPORT_SCHEMA, model)
    except claude_json.ClaudeJSONError as exc:
        raise FeedbackError(str(exc)) from exc


# ------------------------------------------------------------ normalising --- #

def _score(v) -> int:
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 1


def normalise(raw: dict, turns: list[dict], brief: dict | None = None) -> dict:
    """Coerce Claude's JSON into the report schema and add the local stats.

    Scores the brief's criteria and resolves categories against its keys (None: the default brief).
    The report carries the rubric it was scored with (`criteria`, `criteria_hash`, `categories`)."""
    criteria, allowed = brief_mod.criteria_keys(brief), brief_mod.category_keys(brief)
    stations = {st["key"] for st in (brief or {}).get("format", {}).get("stations") or []}
    answers = []
    for a in raw.get("answers") or []:
        if not isinstance(a, dict):
            continue
        scores = {c: _score((a.get("scores") or {}).get(c)) for c in criteria}
        qt = a.get("question_turn")
        question = str(a.get("question") or "")
        entry = {
            "question_turn": qt if isinstance(qt, int) else None,
            "question": question,
            "category": resolve_category(a.get("category"), question, allowed),
            "competency": clean_competency(a.get("competency")),
            "answer_summary": str(a.get("answer_summary") or ""),
            "scores": scores,
            "average": round(sum(scores.values()) / len(criteria), 1),
            "better_answer": str(a.get("better_answer") or ""),
            "tips": [str(t) for t in (a.get("tips") or []) if t][:4],
        }
        if stations and a.get("station") in stations:
            entry["station"] = a["station"]
        answers.append(entry)
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
        **brief_mod.stamp(brief),
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


def _delivery_line(d: dict) -> str:
    from .delivery import delivery_line

    return delivery_line(d)


def _face_moments_md(d: dict | None) -> list[str]:
    from .delivery import face_moment_text

    moments = ((d or {}).get("face") or {}).get("moments") or []
    lines = [f"- {face_moment_text(m)}" + (f", while saying: \u201c{m['quote']}\u201d" if m.get("quote") else "") for m in moments]
    return [*lines, ""] if moments else []


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
    criteria = brief_mod.report_rubric(report)["criteria"]
    for i, a in enumerate(report["answers"], 1):
        s = a["scores"]
        out += [
            f"### {i}. {a['question']}",
            "",
            " · ".join(f"{c['name']} {s.get(c['key'], '–')}/5" for c in criteria) + f" (average {a['average']})",
            "",
            f"**What you said:** {a['answer_summary']}",
            "",
            *([f"**Delivery:** {_delivery_line(a['delivery'])}", ""] if a.get("delivery") else []),
            *_face_moments_md(a.get("delivery")),
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

def session_brief(session: dict) -> dict | None:
    """The session's brief snapshot (None: it ran with the default brief)."""
    import json

    return json.loads(session["brief_json"]) if session.get("brief_json") else None


def turns_needing_words(turns: list[dict], audio_dir=None) -> list[dict]:
    """Spoken candidate turns with no word offsets yet (PLAN-voice.md, V4): every turn with a saved WAV.

    Face data and segments are no longer needed (segments only matter for session-clock labels). With
    ``audio_dir`` (the session's ``<idx>.wav`` folder) a turn without its file is left out, which skips typed
    answers; without it every candidate turn that has no words counts.
    """
    return [t for t in turns if t["speaker"] == "candidate" and t.get("words") is None
            and (audio_dir is None or (Path(audio_dir) / f"{t['idx']}.wav").exists())]


async def _fill_words(session_id: str, turns: list[dict]) -> None:
    """Word offsets from the saved WAVs, on the MLX thread, before the report request. Never fails the report."""
    from . import gpu, stt

    for t in turns_needing_words(turns, db.ANSWERS_DIR / session_id):
        path = db.ANSWERS_DIR / session_id / f"{t['idx']}.wav"
        try:
            t["words"] = await gpu.run(stt.words_from_wav, path)
            db.set_turn_words(session_id, t["idx"], t["words"])
        except Exception as exc:
            log.warning("Word timestamps failed for %s turn %s: %s", session_id, t["idx"], exc)


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
        brief = session_brief(session)  # the brief the session ran with, so a later edit never re-scores it
        await _fill_words(session_id, turns)  # before the request: the voice evidence quotes these words (V4)
        raw = await _ask_claude(_system_prompt(pack, fixes, brief), _transcript(turns), report_schema(brief))
        report = normalise(raw, turns, brief)
        from . import delivery  # imported here: delivery imports this module

        delivery.answer_delivery(report["answers"], turns, db.ANSWERS_DIR / session_id,
                                 db.voice_baseline(exclude_session=session_id),
                                 db.face_baseline(exclude_session=session_id),
                                 targets=brief_mod.targets(report["categories"]),
                                 no_target=brief_mod.untimed_stations(brief))
        db.save_report(session_id, report, to_markdown(report, pack, session, turns))
        db.set_overall_score(session_id, report["overall_score"])
        log.info("Report ready for %s (overall %.1f)", session_id, report["overall_score"])
    except Exception as exc:
        msg = str(exc) if isinstance(exc, FeedbackError) else f"{type(exc).__name__}: {exc}"
        log.warning("Report failed for %s: %s", session_id, msg)
        db.set_report_error(session_id, msg)
