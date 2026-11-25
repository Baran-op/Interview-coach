"""Interview brief (PLAN-brief Phase I): materials in, one reviewed brief out.

The brief says what the interview is (field, role, level), how it runs (format: conversation,
stations or panel), how answers are scored (criteria with 1/3/5 anchors) and what kinds of
question there are (categories). Everything downstream (interviewer, report, prep, Drill,
answer lengths, History) reads the brief, never the raw materials.

With no brief saved, `default_brief(pack)` reproduces today's prompts exactly (the golden tests
prove it). The brief is a cache, built like the prep sheet: a `source_hash` of the inputs, a
cleaning function, one `claude_json.ask_json` call and its own table (`briefs`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import claude_json

PROMPTS_DIR = Path(__file__).parent / "prompts"
VERSION = 1

FORMAT_KINDS = ("conversation", "stations", "panel")
CRITERION_SOURCES = ("provided", "inferred", "default")
ANCHOR_KEYS = ("1", "3", "5")


class BriefError(RuntimeError):
    pass


# ------------------------------------------------------------ the default --- #

# Today's four criteria, word for word from prompts/feedback.txt (description line, 1/3/5 line).
DEFAULT_CRITERIA: list[dict] = [
    {
        "key": "relevance", "name": "Relevance",
        "description": "answers the question that was asked and connects to the job's requirements.",
        "anchors": {"1": "does not answer the question asked.",
                    "3": "answers it, but generic, with little link to this job.",
                    "5": "answers it directly and ties the answer to the job's specific requirements."},
    },
    {
        "key": "structure", "name": "Structure",
        "description": (
            "clear and easy to follow. For behavioural questions, use the STAR shape (Situation, Task, Action, "
            "Result). For \"tell me about yourself\", a short present, past, future story tied to this job (about "
            "1 to 2 minutes). For \"why this company\", specific reasons that show research, checked against the "
            "company notes above. For technical or case questions, a clear approach, steps and conclusion."),
        "anchors": {"1": "rambling or no discernible order.",
                    "3": "an order is there but a part is missing (for example no Result) or it wanders.",
                    "5": "a complete, tight shape that is easy to follow, at a sensible length."},
    },
    {
        "key": "specificity", "name": "Specificity",
        "description": "concrete details, the candidate's own role (\"I\" rather than \"we\"), names of tools, systems and stakeholders.",
        "anchors": {"1": "vague generalities, mostly \"we\" or \"you\".",
                    "3": "some real detail, but the candidate's own part or the names are unclear.",
                    "5": "clear first-person actions with named tools, systems and stakeholders."},
    },
    {
        "key": "evidence", "name": "Evidence",
        "description": "results, numbers and proof that back up the claims.",
        "anchors": {"1": "no outcome or numbers.",
                    "3": "an outcome, but vague or unmeasured.",
                    "5": "measured results clearly caused by the candidate's own actions."},
    },
]

_ROLEPLAY_NOTE = (
    "For a roleplay answer (the interviewer played a client or stakeholder), judge the candidate's behaviour in the "
    "scene as the answer. Good structure is: acknowledge the person's feelings or problem, clarify with a question or "
    "two, propose a plan, and agree the next steps. Do not mark them down for not using STAR, and judge the reflection "
    "at the end as part of the same answer. Score evidence on whether they committed to something concrete (dates, "
    "owners, follow-up).")
_LOGISTICS_NOTE = (
    "For a logistics answer (salary, notice period, availability, location), good is a clear, researched salary range "
    "(not \"whatever you think is fair\" and not an unexplained single number), an honest notice period or start date, "
    "and flexibility stated without being evasive. Score structure on clarity and directness, evidence on whether the "
    "figures are justified.")

# Today's eight categories, in today's order (descriptions from feedback.txt's category sentence).
DEFAULT_CATEGORIES: list[dict] = [
    {"key": "intro", "label": "Intro", "description": "tell me about yourself",
     "structure_hint": "A short present, past, future story tied to this job (about 1 to 2 minutes).",
     "scoring_note": "", "target_seconds": [60, 90]},
    {"key": "motivation", "label": "Motivation", "description": "why this role or company",
     "structure_hint": "Specific reasons that show research.", "scoring_note": "", "target_seconds": [45, 90]},
    {"key": "behavioural", "label": "Behavioural", "description": "past experience, competency questions",
     "structure_hint": "STAR: Situation, Task, Action, Result.", "scoring_note": "", "target_seconds": [90, 150]},
    {"key": "technical", "label": "Technical", "description": "skills, tools, how things work",
     "structure_hint": "A clear approach, steps and conclusion.", "scoring_note": "", "target_seconds": None},
    {"key": "case", "label": "Case", "description": "a business or product problem",
     "structure_hint": "A clear approach, steps and conclusion.", "scoring_note": "", "target_seconds": None},
    {"key": "roleplay", "label": "Role-play", "description": "the interviewer plays a client or stakeholder",
     "structure_hint": "Acknowledge, clarify, propose a plan, agree next steps.", "scoring_note": _ROLEPLAY_NOTE,
     "target_seconds": None},
    {"key": "logistics", "label": "Logistics", "description": "notice period, salary, availability, location",
     "structure_hint": "Clear and direct, with justified figures.", "scoring_note": _LOGISTICS_NOTE,
     "target_seconds": None},
    {"key": "other", "label": "Other", "description": "", "structure_hint": "", "scoring_note": "",
     "target_seconds": None},
]


def default_criteria() -> list[dict]:
    return [{**c, "anchors": dict(c["anchors"]), "source": "default", "scale_note": ""} for c in DEFAULT_CRITERIA]


def default_categories() -> list[dict]:
    return [{**c, "target_seconds": list(c["target_seconds"]) if c["target_seconds"] else None}
            for c in DEFAULT_CATEGORIES]


def default_brief(pack: dict | None = None) -> dict:
    """The brief that reproduces today's interview exactly. Prompts render it in default mode (raw
    material slots), so `candidate_summary` and `candidate_facts` stay empty."""
    pack = pack or {}
    opts = pack.get("options") or {}
    return {
        "version": VERSION,
        "field": "",
        "role": (pack.get("role") or "")[:80],
        "organisation": (pack.get("company") or "")[:80],
        "level": "",
        "format": {"kind": "conversation", "summary": "", "total_minutes": opts.get("minutes") or None,
                   "opening": True, "candidate_questions": True, "panel": [], "stations": []},
        "criteria": default_criteria(),
        "categories": default_categories(),
        "competencies": [], "likely_questions": [], "probes": [], "facts": [],
        "candidate_summary": "", "candidate_facts": "", "assumptions": [],
    }


# --------------------------------------------------------------- hashing --- #

def _sha1(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def source_hash(materials: list[dict]) -> str:
    """SHA-1 over each material's kind, name and stripped text, in order."""
    h = hashlib.sha1()
    for m in materials:
        for part in (m.get("kind") or "", (m.get("name") or "").strip(), (m.get("text") or "").strip()):
            h.update(part.encode("utf-8"))
            h.update(b"\0")
        h.update(b"\1")
    return h.hexdigest()


def criteria_hash(criteria: list[dict]) -> str:
    """SHA-1 of the canonical JSON of [(key, name, description, anchors)]."""
    return _sha1([[c["key"], c["name"], c["description"], c["anchors"]] for c in criteria])


def rubric_hash(rubric: dict) -> str:
    """Criteria plus [(key, description)] of the categories: what freezing compares."""
    return _sha1([criteria_hash(rubric["criteria"]), [[c["key"], c.get("description", "")] for c in rubric["categories"]]])


DEFAULT_CRITERIA_HASH = criteria_hash(DEFAULT_CRITERIA)


def rubric_of(brief: dict) -> dict:
    return {"criteria": brief["criteria"], "categories": brief["categories"]}


# -------------------------------------------------------------- cleaning --- #

def _s(v, cap: int) -> str:
    return " ".join(str(v).split())[:cap].strip() if v is not None else ""


def _text(v, cap: int) -> str:
    """Like _s but keeps line breaks (for longer fields)."""
    if v is None:
        return ""
    lines = [" ".join(line.split()) for line in str(v).strip().splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))[:cap].strip()


def slugify(v, cap: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(v or "").lower()).strip("_")
    return s[:cap].strip("_")


def _unique(key: str, seen: set[str]) -> str:
    out, n = key, 2
    while out in seen:
        out = f"{key[:28]}_{n}"
        n += 1
    seen.add(out)
    return out


def _int(v, lo: int, hi: int) -> int | None:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return default


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _criteria(raw) -> list[dict]:
    out, seen = [], set()
    for c in _list(raw):
        if not isinstance(c, dict):
            continue
        name = _s(c.get("name"), 60)
        key = slugify(c.get("key") or name)
        desc = _text(c.get("description"), 700)
        anchors = c.get("anchors") if isinstance(c.get("anchors"), dict) else {}
        anchors = {k: _s(anchors.get(k), 300) for k in ANCHOR_KEYS}
        if not key or key in seen or not desc or not all(anchors.values()):
            continue
        seen.add(key)
        source = c.get("source") if c.get("source") in CRITERION_SOURCES else "inferred"
        out.append({"key": key, "name": name or key.replace("_", " ").capitalize(),
                    "description": desc, "anchors": anchors, "source": source,
                    "scale_note": _s(c.get("scale_note"), 300) if source == "provided" else ""})
    return out


def _target(v) -> list[int] | None:
    if not isinstance(v, list) or len(v) != 2:
        return None
    lo, hi = _int(v[0], 10, 1800), _int(v[1], 10, 1800)
    return [lo, hi] if lo is not None and hi is not None and lo < hi else None


def _categories(raw) -> list[dict]:
    out, seen = [], set()
    for c in _list(raw):
        if not isinstance(c, dict):
            continue
        label = _s(c.get("label"), 40)
        key = slugify(c.get("key") or label, 24)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "label": label or key.replace("_", " ").capitalize(),
                    "description": _s(c.get("description"), 120), "structure_hint": _s(c.get("structure_hint"), 400),
                    "scoring_note": _s(c.get("scoring_note"), 700), "target_seconds": _target(c.get("target_seconds"))})
    others = [c for c in out if c["key"] != "other"][:9]
    other = next((c for c in out if c["key"] == "other"), None) or {
        "key": "other", "label": "Other", "description": "", "structure_hint": "", "scoring_note": "", "target_seconds": None}
    return others + [other]


def _assumption(section: str, text: str, question: str = "", confirmed: bool = False) -> dict:
    return {"id": "", "section": section, "text": text, "question": question, "answer": "", "confirmed": confirmed}


def clean_brief(raw: dict, frozen: dict | None = None) -> dict:
    """Coerce Claude's (or your edited) JSON into a valid brief. Pure.

    `frozen` ({criteria, categories}) replaces the brief's rubric when the pack's scoring is frozen
    (it has scored sessions), with an assumption saying so.
    """
    raw = raw if isinstance(raw, dict) else {}
    notes: list[dict] = []
    fmt_raw = raw.get("format") if isinstance(raw.get("format"), dict) else {}

    criteria = _criteria(raw.get("criteria"))
    if len(criteria) < 3:
        criteria = default_criteria()
        notes.append(_assumption("criteria", "Fewer than 3 usable criteria were found, so the app's four standard "
                                 "criteria are used (relevance, structure, specificity, evidence).",
                                 "Is there a mark scheme you can add as a material?"))
    elif len(criteria) > 6:
        notes.append(_assumption("criteria", f"The materials had {len(criteria)} criteria; only the first 6 are kept.",
                                 "Which ones should be merged or dropped?"))
        criteria = criteria[:6]
    categories = _categories(raw.get("categories"))
    if len(categories) < 2:
        categories = default_categories()
        notes.append(_assumption("categories", "No usable question categories were found, so the standard ones are used."))
    if frozen:
        if criteria_hash(criteria) != criteria_hash(frozen["criteria"]) or \
                [c["key"] for c in categories] != [c["key"] for c in frozen["categories"]]:
            notes.append(_assumption("criteria", "This pack already has scored sessions, so its criteria and categories "
                                     "were kept as they were to keep History comparable.", "", True))
        criteria = [dict(c) for c in frozen["criteria"]]
        categories = [dict(c) for c in frozen["categories"]]
    keys = {c["key"] for c in categories}

    def cat(v) -> str:
        k = slugify(v, 24)
        return k if k in keys else "other"

    kind = fmt_raw.get("kind") if fmt_raw.get("kind") in FORMAT_KINDS else "conversation"
    stations, seen = [], set()
    if kind == "stations":
        for st in _list(fmt_raw.get("stations"))[:8]:
            if not isinstance(st, dict):
                continue
            name = _s(st.get("name"), 80)
            key = slugify(st.get("key") or name, 24)
            if not key:
                continue
            stations.append({"key": _unique(key, seen), "name": name or key.replace("_", " ").capitalize(),
                             "minutes": _int(st.get("minutes"), 1, 60) or 10, "category": cat(st.get("category")),
                             "brief": _text(st.get("brief"), 600), "scenario": _text(st.get("scenario"), 1500) or None})
        if not stations:
            kind = "conversation"
            notes.append(_assumption("format", "A stations interview was suggested but no stations were usable, so "
                                     "it runs as a conversation.", "What stations are there, and how long is each?"))
    panel = []
    if kind == "panel":
        for p in _list(fmt_raw.get("panel"))[:4]:
            if isinstance(p, dict) and _s(p.get("name"), 60):
                panel.append({"name": _s(p.get("name"), 60), "role": _s(p.get("role"), 80), "focus": _s(p.get("focus"), 200)})
        if len(panel) < 2:
            kind, panel = "conversation", []
            notes.append(_assumption("format", "A panel was suggested but fewer than 2 members were named, so it runs "
                                     "as a conversation with one interviewer.", "Who sits on the panel?"))
    total = sum(st["minutes"] for st in stations) if kind == "stations" else _int(fmt_raw.get("total_minutes"), 5, 180)

    questions = []
    for q in _list(raw.get("likely_questions")):
        if isinstance(q, dict) and _s(q.get("question"), 200):
            questions.append({"question": _s(q["question"], 200), "category": cat(q.get("category")), "why": _s(q.get("why"), 160)})
    strings = lambda v, n, cap: [s for s in (_s(x, cap) for x in _list(v)) if s][:n]  # noqa: E731

    assumptions = []
    for a in _list(raw.get("assumptions")):
        if isinstance(a, dict) and _s(a.get("text"), 300):
            assumptions.append({"id": "", "section": slugify(a.get("section"), 20) or "other",
                                "text": _s(a["text"], 300), "question": _s(a.get("question"), 300),
                                "answer": _s(a.get("answer"), 600), "confirmed": _bool(a.get("confirmed"), False)})
    assumptions = (assumptions + notes)[:16]
    for i, a in enumerate(assumptions, 1):
        a["id"] = f"a{i}"

    return {
        "version": VERSION,
        "field": _s(raw.get("field"), 60),
        "role": _s(raw.get("role"), 80),
        "organisation": _s(raw.get("organisation"), 80),
        "level": _s(raw.get("level"), 60),
        "format": {
            "kind": kind,
            "summary": _s(fmt_raw.get("summary"), 400),
            "total_minutes": total,
            "opening": _bool(fmt_raw.get("opening"), True),
            "candidate_questions": _bool(fmt_raw.get("candidate_questions"), True),
            "panel": panel,
            "stations": stations,
        },
        "criteria": criteria,
        "categories": categories,
        "competencies": strings(raw.get("competencies"), 12, 40),
        "likely_questions": questions[:15],
        "probes": strings(raw.get("probes"), 8, 150),
        "facts": strings(raw.get("facts"), 15, 150),
        "candidate_summary": _text(raw.get("candidate_summary"), 1200),
        "candidate_facts": _text(raw.get("candidate_facts"), 4000),
        "assumptions": assumptions,
    }


def to_confirm(brief: dict) -> int:
    return sum(1 for a in brief.get("assumptions") or [] if not a.get("confirmed"))


def meta(brief: dict | None, stale: bool = False) -> dict:
    """`brief_meta` for GET /packs/{id}: enough for Setup and Interview without a second request."""
    if not brief:
        return {"exists": False, "kind": "conversation", "total_minutes": None, "stations": [], "stale": False,
                "to_confirm": 0}
    f = brief["format"]
    return {"exists": True, "kind": f["kind"], "total_minutes": f["total_minutes"],
            "stations": [{"name": s["name"], "minutes": s["minutes"]} for s in f["stations"]],
            "stale": stale, "to_confirm": to_confirm(brief)}


# -------------------------------------------------------------- rendering --- #

def render_criteria(criteria: list[dict]) -> str:
    """The criteria lines shared by the report and drill prompts."""
    lines = []
    for c in criteria:
        a = c["anchors"]
        lines.append(f"  - {c['key']}: {c['description']}")
        lines.append(f"    1 = {a['1']} 3 = {a['3']} 5 = {a['5']}")
        if c.get("scale_note"):
            lines.append(f"    (The candidate's mark scheme: {c['scale_note']})")
    return "\n".join(lines)


def category_sentence(categories: list[dict]) -> str:
    """'one of intro (tell me about yourself), ... or other.'"""
    parts = [f"{c['key']} ({c['description']})" if c.get("description") else c["key"] for c in categories]
    return "one of " + (", ".join(parts[:-1]) + " or " + parts[-1] if len(parts) > 1 else parts[0])


def render_context(brief: dict) -> str:
    """The interviewer's view of a generated brief (2e): no criteria, the interviewer doesn't score."""
    f = brief["format"]
    head = brief["role"] or "the role"
    if brief["organisation"]:
        head += f" at {brief['organisation']}"
    lines = [f"The interview: {head}" + (f" ({brief['field']})" if brief["field"] else "")
             + (f". Level: {brief['level']}." if brief["level"] else ".")]
    if f["summary"]:
        lines += ["", f"Format: {f['summary']}"]
    if brief["competencies"]:
        lines += ["", "What they assess: " + "; ".join(brief["competencies"]) + "."]
    if brief["likely_questions"]:
        lines += ["", "Question ideas (not a script; use your judgement):"]
        lines += [f"- {q['question']}" for q in brief["likely_questions"][:8]]
    if brief["probes"]:
        lines += ["", "What a sceptical interviewer would probe:"] + [f"- {p}" for p in brief["probes"]]
    if brief["facts"]:
        lines += ["", "Facts about the organisation (for answering the candidate's questions):"]
        lines += [f"- {x}" for x in brief["facts"]]
    lines += ["", "About the candidate:", brief["candidate_summary"] or "(not provided)"]
    return "\n".join(lines)


_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def criteria_keys(brief: dict | None) -> list[str]:
    return [c["key"] for c in (brief or default_brief())["criteria"]]


def category_keys(brief: dict | None) -> list[str]:
    return [c["key"] for c in (brief or default_brief())["categories"]]


def targets(categories: list[dict]) -> dict[str, tuple[int, int]]:
    """{category key: (min, max) seconds} for the categories that have a target answer length."""
    return {c["key"]: tuple(c["target_seconds"]) for c in categories if c.get("target_seconds")}


def legacy_context(slots: dict, notes_label: str = "Company notes (research the candidate was given)",
                   notes_empty: str = "(not provided)") -> str:
    """Today's JD / CV / company notes block (default mode only)."""
    return (f"Job description:\n{slots['jd'] or '(not provided)'}\n\n"
            f"Candidate profile (CV):\n{slots['profile'] or '(not provided)'}\n\n"
            f"{notes_label}:\n{slots['company_notes'] or notes_empty}")


def scoring_context(brief: dict) -> str:
    """What the report, Drill and prep see of a generated brief: the interview, and the candidate facts."""
    f = brief["format"]
    head = brief["role"] or "the role"
    if brief["organisation"]:
        head += f" at {brief['organisation']}"
    lines = [f"The interview: {head}" + (f" ({brief['field']})" if brief["field"] else "")
             + (f". Level: {brief['level']}." if brief["level"] else ".")]
    if f["summary"]:
        lines.append(f"Format: {f['summary']}")
    if brief["competencies"]:
        lines.append("What it assesses: " + "; ".join(brief["competencies"]) + ".")
    if brief["facts"]:
        lines += ["", "Facts about the organisation (from the candidate's materials):"] + [f"- {x}" for x in brief["facts"]]
    lines += ["", "Candidate facts (from their CV and other materials; the only facts about the candidate you may use):",
              brief["candidate_facts"] or brief["candidate_summary"] or "(not provided)"]
    return "\n".join(lines)


def json_scores(brief: dict | None) -> str:
    return "{" + ", ".join(f'"{k}": 3' for k in criteria_keys(brief)) + "}"


def category_notes(categories: list[dict]) -> str:
    return "".join(f"- {c['scoring_note']}\n" for c in categories if c.get("scoring_note"))


def followup_criteria(brief: dict | None) -> str:
    keys = criteria_keys(brief)
    if "specificity" in keys and "evidence" in keys:
        return "specificity and evidence"
    return "the criteria about detail and evidence"


def entries_rule(brief: dict | None) -> str:
    """The report's rule for what gets an entry in "answers"."""
    f = (brief or default_brief())["format"]
    if f["kind"] == "stations":
        return ('- Make one entry in "answers" per STATION the interview reached, in order. The interviewer opens each '
                'station with a line such as "Station 2: ...". "question" is the station name and the first line of its '
                'scenario, "category" is the station\'s category, "station" is the station key given in the list below, and '
                '"question_turn" is the interviewer turn that opened it. Fold everything said in the station (the scenario, '
                'follow-ups and answers) into its entry. A station that was not reached gets no entry; say so in "summary". '
                'Skip the welcome and the close.' + (' Also judge the questions the candidate asked at the end, in "summary" '
                                                      'only (not as an entry).' if f["candidate_questions"] else '')
                + "\n  Stations: " + "; ".join(f"{s['key']} = {s['name']} ({s['category']}, {s['minutes']} min)" for s in f["stations"]) + ".")
    out = '- Make one entry in "answers" per MAIN question the interviewer asked.'
    if f["opening"]:
        out += (' This includes the opening "tell me about yourself" and the "why this role / why this company" '
                'question: score them like any other.')
    else:
        out += ' This includes the "why this role / why this company" question: score it like any other.'
    out += (" Fold the interviewer's follow-up questions and the candidate's follow-up answers into that main question's "
            "entry. Skip the greeting, small talk and the closing part.")
    if f["candidate_questions"]:
        out += ' Also judge the questions the candidate asked at the end, in "summary" only (not as an entry).'
    return out


def scoring_values(brief: dict | None) -> dict[str, str]:
    """Slots shared by the report and drill prompts. `brief` None is the default brief (today's text)."""
    b = brief or default_brief()
    stations = b["format"]["kind"] == "stations"
    example = "behavioural" if "behavioural" in category_keys(b) else category_keys(b)[0]
    return {
        "criteria_block": render_criteria(b["criteria"]),
        "n_criteria": _NUMBER_WORDS.get(len(b["criteria"]), str(len(b["criteria"]))),
        "json_scores": json_scores(b),
        "category_sentence": category_sentence(b["categories"]),
        "category_notes": category_notes(b["categories"]),
        "entries_rule": entries_rule(b),
        "followup_criteria": followup_criteria(b),
        "example_category": example,
        "station_field": '\n      "station": "station key",' if stations else "",
        "turn_note": ('"question_turn" is the turn number of the interviewer line that opened the station.' if stations else
                      '"question_turn" is the turn number of the interviewer line that asked the main question.'),
    }


def report_rubric(report: dict | None) -> dict:
    """The rubric a report (or drill result) was scored with. Older ones carry none: the default
    four criteria and eight categories. Every reader goes through here."""
    r = report or {}
    crit = r.get("criteria") or [{"key": c["key"], "name": c["name"]} for c in DEFAULT_CRITERIA]
    cats = r.get("categories") or [{"key": c["key"], "label": c["label"], "target_seconds": c["target_seconds"]}
                                   for c in DEFAULT_CATEGORIES]
    return {"criteria": crit, "criteria_hash": r.get("criteria_hash") or DEFAULT_CRITERIA_HASH, "categories": cats}


def untimed_stations(brief: dict | None) -> set[str]:
    """Stations whose answers get no target length: a scenario station longer than 5 minutes."""
    return {st["key"] for st in ((brief or {}).get("format") or {}).get("stations") or []
            if st.get("scenario") and st["minutes"] > 5}


def stamp(brief: dict | None) -> dict:
    """The rubric keys stored on each new report and drill attempt."""
    b = brief or default_brief()
    return {"criteria": [{"key": c["key"], "name": c["name"]} for c in b["criteria"]],
            "criteria_hash": criteria_hash(b["criteria"]),
            "categories": [{"key": c["key"], "label": c["label"], "target_seconds": c["target_seconds"]}
                           for c in b["categories"]]}


# ------------------------------------------------------------- generation --- #

def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props)}


_S = {"type": "string"}
_SS = {"type": "array", "items": _S}
SCHEMA = _obj({
    "field": _S, "role": _S, "organisation": _S, "level": _S,
    "format": _obj({
        "kind": {"type": "string", "enum": list(FORMAT_KINDS)},
        "summary": _S,
        "total_minutes": {"type": ["integer", "null"]},
        "opening": {"type": "boolean"},
        "candidate_questions": {"type": "boolean"},
        "panel": {"type": "array", "items": _obj({"name": _S, "role": _S, "focus": _S})},
        "stations": {"type": "array", "items": _obj({
            "key": _S, "name": _S, "minutes": {"type": "integer"}, "category": _S, "brief": _S,
            "scenario": {"type": ["string", "null"]}})},
    }),
    "criteria": {"type": "array", "items": _obj({
        "key": _S, "name": _S, "description": _S,
        "anchors": _obj({k: _S for k in ANCHOR_KEYS}),
        "source": {"type": "string", "enum": list(CRITERION_SOURCES)},
        "scale_note": _S})},
    "categories": {"type": "array", "items": _obj({
        "key": _S, "label": _S, "description": _S, "structure_hint": _S, "scoring_note": _S,
        "target_seconds": {"type": ["array", "null"], "items": {"type": "integer"}}})},
    "competencies": _SS,
    "likely_questions": {"type": "array", "items": _obj({"question": _S, "category": _S, "why": _S})},
    "probes": _SS,
    "facts": _SS,
    "candidate_summary": _S,
    "candidate_facts": _S,
    "assumptions": {"type": "array", "items": _obj({"section": _S, "text": _S, "question": _S})},
})


def _materials_block(materials: list[dict]) -> str:
    return "\n\n".join(f"### {m['name']} (kind: {m['kind']})\n{m['text'].strip()}" for m in materials) or "(none)"


def answers_block(previous: dict | None) -> str:
    """Your replies to the previous brief's questions, for Regenerate (2c)."""
    rows = [a for a in (previous or {}).get("assumptions") or [] if a.get("answer") or a.get("confirmed")]
    if not rows:
        return "(none yet)"
    out = []
    for a in rows:
        reply = a.get("answer") or "(confirmed as written)"
        out.append(f"- You assumed: {a['text']}" + (f" You asked: {a['question']}" if a.get("question") else "")
                   + f"\n  The candidate's answer: {reply}")
    return "\n".join(out)


def system_prompt(pack: dict, materials: list[dict], previous: dict | None = None) -> str:
    defaults = {"criteria": [{k: c[k] for k in ("key", "name", "description", "anchors")} for c in DEFAULT_CRITERIA],
                "categories": DEFAULT_CATEGORIES}
    values = {
        "role": pack.get("role") or "(not given)",
        "company": pack.get("company") or "(not given)",
        "materials": _materials_block(materials),
        "defaults": json.dumps(defaults, indent=1, ensure_ascii=False),
        "answers": answers_block(previous),
    }
    text = (PROMPTS_DIR / "brief.txt").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def model() -> str | None:
    return os.environ.get("BRIEF_MODEL") or os.environ.get("FEEDBACK_MODEL") or os.environ.get("INTERVIEWER_MODEL") or None


async def write(pack: dict, materials: list[dict], previous: dict | None = None, frozen: dict | None = None) -> dict:
    """Generate the brief: one Claude request. `previous` carries your answers to its questions."""
    if not any((m.get("text") or "").strip() for m in materials):
        raise BriefError("Add some materials to the pack first")
    try:
        raw = await claude_json.ask_json(system_prompt(pack, materials, previous),
                                         "Write the interview brief JSON now.", SCHEMA, model())
    except claude_json.ClaudeJSONError as exc:
        raise BriefError(str(exc)) from exc
    return clean_brief(raw, frozen)
