"""Prep sheet per pack (PLAN.md section 7): likely questions, CV gaps, STAR stories, questions to ask.

Pure helpers (source_hash, sheet cleaning, drill questions) plus the single Claude request that
writes the sheet. Routes live in main.py.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import claude_json, materials
from .categories import resolve_category

PROMPTS_DIR = Path(__file__).parent / "prompts"


class PrepError(RuntimeError):
    pass


def source_hash(pack: dict) -> str:
    """SHA-1 of the JD, CV and company notes (the materials' slot view, so a legacy pack hashes
    as before): changes when the sheet's sources change."""
    h = hashlib.sha1()
    slots = materials.legacy_slots(pack)
    for field in ("jd", "profile", "company_notes"):
        h.update((slots[field] or "").strip().encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props)}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}

SCHEMA = _obj({
    "likely_questions": {"type": "array", "items": _obj({"question": _STR, "category": _STR, "why": _STR})},
    "gaps": {"type": "array", "items": _obj({
        "requirement": _STR, "cv_evidence": {"type": ["string", "null"]}, "how_to_address": _STR})},
    "stories": {"type": "array", "items": _obj({
        "title": _STR, "competencies": _STRS, "situation": _STR, "task": _STR,
        "action": _STR, "result": _STR, "numbers": _STRS})},
    "questions_to_ask": _STRS,
})


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _strings(v) -> list[str]:
    return [_s(x) for x in v if _s(x)] if isinstance(v, list) else []


def clean_sheet(raw: dict) -> dict:
    """Coerce Claude's JSON into the stored shape (drops empty entries, fixes categories)."""
    questions = []
    for q in raw.get("likely_questions") or []:
        text = _s(q.get("question")) if isinstance(q, dict) else ""
        if text:
            questions.append({"question": text, "category": resolve_category(q.get("category"), text),
                              "why": _s(q.get("why"))})
    gaps = []
    for g in raw.get("gaps") or []:
        if isinstance(g, dict) and _s(g.get("requirement")):
            gaps.append({"requirement": _s(g["requirement"]), "cv_evidence": _s(g.get("cv_evidence")) or None,
                         "how_to_address": _s(g.get("how_to_address"))})
    stories = []
    for st in raw.get("stories") or []:
        if isinstance(st, dict) and _s(st.get("title")):
            stories.append({"title": _s(st["title"]), "competencies": _strings(st.get("competencies")),
                            **{k: _s(st.get(k)) for k in ("situation", "task", "action", "result")},
                            "numbers": _strings(st.get("numbers"))})
    return {"likely_questions": questions, "gaps": gaps, "stories": stories,
            "questions_to_ask": _strings(raw.get("questions_to_ask"))}


def drill_questions(sheet: dict | None) -> list[dict]:
    """The sheet's likely questions in the drill list's shape (source `prep`)."""
    return [{"question": q["question"], "category": q.get("category"), "source": "prep"}
            for q in (sheet or {}).get("likely_questions") or [] if q.get("question")]


def system_prompt(pack: dict) -> str:
    slots = materials.legacy_slots(pack)
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "jd": slots["jd"] or "(not provided)",
        "profile": slots["profile"] or "(not provided)",
        "company_notes": slots["company_notes"] or "(not provided)",
    }
    text = (PROMPTS_DIR / "prep.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


async def write(pack: dict) -> dict:
    model = os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None
    try:
        raw = await claude_json.ask_json(system_prompt(pack), "Write the prep sheet JSON now.", SCHEMA, model)
    except claude_json.ClaudeJSONError as exc:
        raise PrepError(str(exc)) from exc
    sheet = clean_sheet(raw)
    if not sheet["likely_questions"]:
        raise PrepError("Claude returned an empty prep sheet; try again")
    return sheet
