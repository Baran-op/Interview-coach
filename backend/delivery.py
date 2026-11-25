"""Per-answer delivery stats, computed locally (see PLAN.md section 5).

Text part only for now: ``text_stats``. Pure functions, no I/O.
"""

import re

from .feedback import filler_words

# Target answer length in seconds (min, max) by question type; other types have none.
TARGET_SECONDS: dict[str, tuple[int, int]] = {
    "intro": (60, 90),
    "motivation": (45, 90),
    "behavioural": (90, 150),
}

_APOS = r"['’]"

# Hedges. None of these may match anything in feedback._FILLER_RE (um, you know, kind of, ...).
_HEDGE_RE = re.compile(
    r"\b(?:i\s+think|i\s+guess|i\s+suppose|i\s+feel\s+like|maybe|perhaps|probably|hopefully)\b",
    re.IGNORECASE,
)

_I_RE = re.compile(rf"\b(?:i|i{_APOS}m|i{_APOS}ve|i{_APOS}d|i{_APOS}ll|me|my)\b", re.IGNORECASE)
_WE_RE = re.compile(rf"\b(?:we|we{_APOS}re|we{_APOS}ve|we{_APOS}d|we{_APOS}ll|us|our)\b", re.IGNORECASE)

_NUM_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    "sixteen|seventeen|eighteen|nineteen|twenty|hundred|thousand|million|billion|percent|half|double"
)
# One figure = optional currency symbol, digits or a number word, then any scale suffixes
# ("%", "k", "m", "bn", "percent", "hundred", ...). So "£5m", "10 percent" and
# "two hundred thousand" each count once.
_NUMBER_RE = re.compile(
    rf"(?:[£$€]\s?)?(?:\d[\d,]*(?:\.\d+)?|\b(?:{_NUM_WORDS})\b)"
    rf"(?:%|(?:k|m|bn)\b|\s+(?:per\s?cent|{_NUM_WORDS})\b)*",
    re.IGNORECASE,
)


def text_stats(text: str) -> dict:
    """Counts for one answer's text: words, fillers, hedges, I vs we, numbers."""
    return {
        "words": len(text.split()),
        "fillers": filler_words([text])["count"],
        "hedges": len(_HEDGE_RE.findall(text)),
        "i_count": len(_I_RE.findall(text)),
        "we_count": len(_WE_RE.findall(text)),
        "numbers": len(_NUMBER_RE.findall(text)),
    }
