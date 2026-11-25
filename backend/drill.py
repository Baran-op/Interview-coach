"""Drill mode backend (PLAN.md section 1): one question, scored now, try again.

Pure helpers (question_key, question list assembly, result building) plus the single Claude
request that scores an attempt. Routes live in main.py.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

from . import claude_json, db, delivery, prep
from .feedback import CRITERIA, _score

log = logging.getLogger("interview-coach.drill")
PROMPTS_DIR = Path(__file__).parent / "prompts"

WEAK_AVERAGE = 2.5  # report questions averaging this or lower are offered for drilling

# (question template, category). {company} falls back to "this company".
STARTERS: list[tuple[str, str]] = [
    ("Tell me about yourself.", "intro"),
    ("Why this role?", "motivation"),
    ("Why {company}?", "motivation"),
    ("Why are you looking to move now?", "motivation"),
    ("What's a weakness you're working on?", "behavioural"),
]


class DrillError(RuntimeError):
    pass


def question_key(question: str) -> str:
    """First 12 hex chars of the SHA-1 of the question: lower-cased, punctuation and extra spaces removed."""
    norm = re.sub(r"[^\w\s]", "", (question or "").lower().replace("_", " "))
    norm = " ".join(norm.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------- question list --- #

def starter_questions(pack: dict) -> list[dict]:
    company = (pack.get("company") or "").strip() or "this company"
    return [{"question": q.replace("{company}", company), "category": c, "source": "starter"} for q, c in STARTERS]


def weak_report_questions(reports: list[dict]) -> list[dict]:
    """Main questions with an average <= WEAK_AVERAGE, newest session first, one per question key.

    `reports` is a list of report dicts (with "answers"), newest first.
    """
    out, seen = [], set()
    for report in reports:
        for a in (report or {}).get("answers") or []:
            question = str(a.get("question") or "").strip()
            avg = a.get("average")
            if not question or not isinstance(avg, (int, float)) or avg > WEAK_AVERAGE:
                continue
            key = question_key(question)
            if key in seen:
                continue
            seen.add(key)
            out.append({"question": question, "category": a.get("category"), "source": "report"})
    return out


def _avg(attempt: dict) -> float | None:
    return ((attempt or {}).get("result") or {}).get("average")


def assemble_questions(pack: dict, reports: list[dict], attempts: list[dict],
                       prep_sheet: dict | None = None) -> list[dict]:
    """Starters, weak report questions, prep questions, then custom questions that have attempts.

    `attempts` is the pack's attempts, oldest first. Each entry gets `key`, the attempt count and
    the latest and best attempt averages (None until there is one). `prep_sheet` is the pack's
    saved prep sheet, whose likely questions come in with source `prep`.
    """
    candidates = starter_questions(pack) + weak_report_questions(reports) + prep.drill_questions(prep_sheet)
    by_key: dict[str, list[dict]] = {}
    for a in attempts:
        by_key.setdefault(a["question_key"], []).append(a)
    out, seen = [], set()
    for c in candidates:
        key = question_key(c["question"])
        if key not in seen:
            seen.add(key)
            out.append({**c, "key": key})
    for a in attempts:  # questions the user typed themselves
        if a["question_key"] not in seen:
            seen.add(a["question_key"])
            out.append({"key": a["question_key"], "question": a["question"],
                        "category": a.get("category"), "source": "custom"})
    for q in out:
        mine = by_key.get(q["key"], [])
        scores = [s for s in (_avg(a) for a in mine) if s is not None]
        q["attempts"] = len(mine)
        q["latest"] = _avg(mine[-1]) if mine else None
        q["best"] = max(scores) if scores else None
    return out


# ---------------------------------------------------------------- scoring --- #

SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {c: {"type": "integer", "minimum": 1, "maximum": 5} for c in CRITERIA},
            "required": list(CRITERIA),
        },
        "tips": {"type": "array", "items": {"type": "string"}},
        "improved": {"type": "array", "items": {"type": "string"}},
        "better_answer": {"type": "string"},
    },
    "required": ["scores", "tips", "improved", "better_answer"],
}


def system_prompt(pack: dict) -> str:
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "jd": pack.get("jd") or "(not provided)",
        "profile": pack.get("profile") or "(not provided)",
        "company_notes": pack.get("company_notes") or "(not provided)",
    }
    text = (PROMPTS_DIR / "drill.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _length(seconds: float | None, text: str) -> str:
    words = len(text.split())
    return f"{round(seconds)} s, {words} words" if seconds else f"{words} words"


def user_prompt(question: str, category: str, answer: str, seconds: float | None, previous: dict | None) -> str:
    parts = [f"Question ({category}): {question}", "", f"Answer ({_length(seconds, answer)}):", answer]
    if previous:
        res = previous.get("result") or {}
        scores = res.get("scores") or {}
        parts += [
            "",
            f"Previous attempt ({_length(previous.get('seconds'), previous['answer_text'])}), "
            f"average {res.get('average')}, scores "
            + ", ".join(f"{c} {scores.get(c)}" for c in CRITERIA) + ":",
            previous["answer_text"],
        ]
    parts += ["", "Return the scoring JSON now."]
    return "\n".join(parts)


def build_result(raw: dict, answer: str, seconds: float | None) -> dict:
    """Coerce Claude's JSON: clamp scores, average locally, attach local text stats."""
    scores = {c: _score((raw.get("scores") or {}).get(c)) for c in CRITERIA}
    return {
        "scores": scores,
        "average": round(sum(scores.values()) / len(CRITERIA), 1),
        "tips": [str(t) for t in (raw.get("tips") or []) if t][:4],
        "improved": [str(t) for t in (raw.get("improved") or []) if t][:4],
        "better_answer": str(raw.get("better_answer") or ""),
        "delivery": {**delivery.text_stats(answer), "seconds": seconds},
    }


async def score(pack: dict, question: str, category: str, answer: str,
                seconds: float | None, previous: dict | None) -> dict:
    model = os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None
    try:
        raw = await claude_json.ask_json(
            system_prompt(pack), user_prompt(question, category, answer, seconds, previous), SCHEMA, model)
    except claude_json.ClaudeJSONError as exc:
        raise DrillError(str(exc)) from exc
    return build_result(raw, answer, seconds)


def questions_for_pack(pack: dict) -> list[dict]:
    reports = []
    for s in db.list_sessions(limit=1000, pack_id=pack["id"]):  # newest first
        r = (db.get_report(s["id"]) or {}).get("report")
        if r:
            reports.append(r)
    record = db.get_prep(pack["id"])
    return assemble_questions(pack, reports, db.list_attempts(pack["id"]), (record or {}).get("sheet"))
