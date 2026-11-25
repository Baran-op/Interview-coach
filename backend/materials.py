"""Pack materials (PLAN-brief I1): any number of named texts, each with a kind.

Pure helpers only; storage lives in db.py. A pack saved before materials existed has no rows and
is shown as up to three synthetic materials built from its `jd`, `profile` and `company_notes`
columns, so it keeps working, byte for byte, without rewriting the database.
"""

from __future__ import annotations

import re

KINDS = ("job", "candidate", "organisation", "format", "other")
SOURCES = ("paste", "pdf", "text_file", "research")

MAX_PACK_CHARS = 150_000   # about 37k tokens: fits the brief call comfortably
MAX_NAME_CHARS = 80

# (legacy column, kind, name) for the synthetic materials of a legacy pack.
_LEGACY = (("jd", "job", "Job description"), ("profile", "candidate", "CV"),
           ("company_notes", "organisation", "Company notes"))

# Default-mode slots: which kinds fill which legacy template slot.
SLOT_KINDS = {"jd": ("job", "format", "other"), "profile": ("candidate",), "company_notes": ("organisation",)}

# Whisper hint order: your own words first, then the job, then the rest.
HINT_ORDER = ("candidate", "job", "format", "organisation", "other")

_KIND_RULES = (
    ("candidate", r"\bcv\b|resum|curriculum|cover.?letter|portfolio|my.?profile|linkedin"),
    ("format", r"mark.?scheme|marking|person.?spec|station|format|rubric|criteria|assessment|selection"),
    ("organisation", r"company|organi[sz]ation|about.?us|annual.?report|values|mission|research|company.?notes"),
    ("job", r"\bjd\b|job|advert|vacancy|posting|role|description|spec"),
)


def guess_kind(name: str) -> str:
    """A kind from a file or material name ("cv.pdf" -> candidate, "Mark scheme" -> format)."""
    n = re.sub(r"[_\-.]+", " ", (name or "").lower())
    for kind, pattern in _KIND_RULES:
        if re.search(pattern, n):
            return kind
    return "other"


def synthetic(pack: dict) -> list[dict]:
    """The read-only materials of a legacy pack, from its three text columns (empty ones left out)."""
    out = []
    for column, kind, name in _LEGACY:
        text = pack.get(column) or ""
        if text:
            out.append({"id": f"legacy-{column}", "position": len(out), "name": name, "kind": kind,
                        "source": "paste", "text": text, "synthetic": True})
    return out


def of_pack(pack: dict) -> list[dict]:
    """The pack's materials: stored ones when `materials` is attached and non-empty, else synthetic."""
    stored = pack.get("materials")
    return stored if stored else synthetic(pack)


def _join(items: list[dict]) -> str:
    if len(items) == 1:
        return items[0]["text"]
    return "\n\n".join(f"### {m['name']}\n{m['text']}" for m in items)


def legacy_slots(pack: dict) -> dict[str, str]:
    """{jd, profile, company_notes} for the default-brief prompts, mapped from the materials by kind.

    One material in a slot is inserted as is (so a legacy pack renders exactly as before); several
    each get a `### <name>` header. An empty slot is "" (the prompt shows its own placeholder).
    """
    mats = of_pack(pack)
    return {slot: _join([m for m in mats if m["kind"] in kinds]) if any(m["kind"] in kinds for m in mats) else ""
            for slot, kinds in SLOT_KINDS.items()}


def hint_texts(pack: dict) -> list[str]:
    """Material texts in Whisper-hint priority order (candidate, job, format, organisation, other)."""
    mats = of_pack(pack)
    return [m["text"] for kind in HINT_ORDER for m in mats if m["kind"] == kind]


def total_chars(materials: list[dict]) -> int:
    return sum(len(m.get("text") or "") for m in materials)


def has_text(pack: dict) -> bool:
    return any((m.get("text") or "").strip() for m in of_pack(pack))


def clean(items: list[dict]) -> list[dict]:
    """Coerce posted materials: trimmed names (capped), known kind and source, non-empty text."""
    out = []
    for m in items:
        text = str(m.get("text") or "")
        if not text.strip():
            continue
        name = " ".join(str(m.get("name") or "").split())[:MAX_NAME_CHARS] or "Notes"
        kind = m.get("kind") if m.get("kind") in KINDS else guess_kind(name)
        source = m.get("source") if m.get("source") in SOURCES else "paste"
        out.append({"name": name, "kind": kind, "source": source, "text": text})
    return out
