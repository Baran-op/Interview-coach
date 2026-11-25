"""Question categories (PLAN 3c): a fixed vocabulary plus a fallback from the question text."""

from __future__ import annotations

import re

CATEGORIES = ("intro", "motivation", "behavioural", "technical", "case", "roleplay", "logistics", "other")

_INTRO_RE = re.compile(r"about yourself|walk me through your (?:cv|resume|background|career)|introduce yourself", re.I)
_WHY_RE = re.compile(r"\bwhy\b|what (?:attracts|draws|interests|excites) you|\bmotivat", re.I)
_TARGET_RE = re.compile(r"\b(?:role|position|job|company|us|team|join|apply|applying|here|organi[sz]ation)\b", re.I)


def category_from_question(question: str) -> str:
    """Guess a category from the question text alone."""
    q = question or ""
    if _INTRO_RE.search(q):
        return "intro"
    if _WHY_RE.search(q) and _TARGET_RE.search(q):
        return "motivation"
    return "other"


def resolve_category(category, question: str) -> str:
    """A valid category as is (case-insensitive), otherwise the fallback from the question."""
    c = str(category or "").strip().lower()
    return c if c in CATEGORIES else category_from_question(question)


def clean_competency(value) -> str:
    return " ".join(str(value or "").split())[:40]
