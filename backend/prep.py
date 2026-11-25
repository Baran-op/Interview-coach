"""Prep sheet per pack (PLAN.md section 7): likely questions, CV gaps, STAR stories, questions to ask.

Pure helpers (source_hash, sheet cleaning, drill questions) plus the single Claude request that
writes the sheet. Routes live in main.py.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import json
import re

from . import brief as brief_mod
from . import claude_json, materials
from .categories import CATEGORIES, resolve_category

PROMPTS_DIR = Path(__file__).parent / "prompts"


class PrepError(RuntimeError):
    pass


def source_hash(pack: dict, brief: dict | None = None) -> str:
    """What the sheet was written from: with a brief, the SHA-1 of the brief JSON (editing the brief
    marks the sheet stale); without, the SHA-1 of the JD, CV and company notes (the materials' slot
    view, so existing sheets of legacy packs are not marked stale)."""
    if brief is not None:
        return hashlib.sha1(json.dumps(brief, sort_keys=True).encode("utf-8")).hexdigest()
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


def clean_sheet(raw: dict, allowed=CATEGORIES) -> dict:
    """Coerce Claude's JSON into the stored shape (drops empty entries, resolves categories against `allowed`)."""
    questions = []
    for q in raw.get("likely_questions") or []:
        text = _s(q.get("question")) if isinstance(q, dict) else ""
        if text:
            questions.append({"question": text, "category": resolve_category(q.get("category"), text, allowed),
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


def wants_stories(brief: dict | None) -> bool:
    """STAR stories only when some category's expected answer shape uses STAR (always for the default brief)."""
    return brief is None or any(re.search(r"\bSTAR\b", c.get("structure_hint") or "") for c in brief["categories"])


def wants_questions_to_ask(brief: dict | None) -> bool:
    return brief is None or brief["format"]["candidate_questions"]


def _brief_sections(brief: dict) -> str:
    f = brief["format"]
    likely = "\n".join(f"  - {q['question']} ({q['category']})" for q in brief["likely_questions"]) or "  (none listed)"
    stories = ("6 to 8 STAR stories built ONLY from the candidate facts. Never invent achievements, employers, tools or "
               "numbers: where a detail is missing, write a placeholder in square brackets, such as [team size] or "
               "[% improvement]. \"competencies\" are 1 to 3 of the brief's competencies. \"numbers\" lists the figures "
               "from the candidate facts used in the story (empty list if none). Each of situation, task, action and "
               "result is one or two sentences, with \"I\" rather than \"we\"."
               if wants_stories(brief) else "an empty list: this interview's answers are not STAR-shaped.")
    asks = ("4 to 6 sharp questions for the candidate to ask the interviewer, specific to this role and organisation, using "
            "the facts about the organisation where they help. No questions about salary or holidays."
            if wants_questions_to_ask(brief) else "an empty list: this interview has no time for the candidate's questions.")
    opening = (' Include "Tell me about yourself" and a question on why this role and organisation.'
               if f["opening"] else ' Do not include "Tell me about yourself"; this interview does not open with it.')
    values = {
        "likely": likely,
        "probes": (": " + "; ".join(brief["probes"])) if brief["probes"] else "",
        "opening": opening,
        "categories": ", ".join(brief_mod.category_keys(brief)),
        "competencies": "; ".join(brief["competencies"]) or "(none listed: use the main things the interview assesses)",
        "stories": stories,
        "questions_to_ask": asks,
    }
    text = (PROMPTS_DIR / "prep_sections_brief.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def system_prompt(pack: dict, brief: dict | None = None) -> str:
    """The prep prompt. `brief` is the pack's current brief; None renders today's prompt exactly."""
    if brief is None:
        context = brief_mod.legacy_context(materials.legacy_slots(pack))
        sections = (PROMPTS_DIR / "prep_sections.txt").read_text(encoding="utf-8")
    else:
        context, sections = brief_mod.scoring_context(brief), _brief_sections(brief)
    values = {
        "role": pack.get("role") or "the role",
        "company": pack.get("company") or "the company",
        "context": context,
        "sections": sections,
    }
    text = (PROMPTS_DIR / "prep.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


async def write(pack: dict, brief: dict | None = None) -> dict:
    model = os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None
    try:
        raw = await claude_json.ask_json(system_prompt(pack, brief), "Write the prep sheet JSON now.", SCHEMA, model)
    except claude_json.ClaudeJSONError as exc:
        raise PrepError(str(exc)) from exc
    sheet = clean_sheet(raw, brief_mod.category_keys(brief))
    if not wants_stories(brief):
        sheet["stories"] = []
    if not wants_questions_to_ask(brief):
        sheet["questions_to_ask"] = []
    if not sheet["likely_questions"]:
        raise PrepError("Claude returned an empty prep sheet; try again")
    return sheet
