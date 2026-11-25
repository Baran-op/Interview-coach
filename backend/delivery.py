"""Per-answer delivery stats, computed locally (see PLAN.md section 5).

``text_stats`` is pure; ``audio_stats`` reads one WAV; ``answer_delivery`` assembles the
per-answer ``delivery`` objects for a report.
"""

import re
import wave
from pathlib import Path

import numpy as np

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


FRAME_S = 0.03
_BRIDGE_FRAMES = 7  # dips shorter than ~200 ms are gaps between words, not pauses


def audio_stats(wav_path, span_s: float | None = None) -> dict | None:
    """Speaking and pause time from 30 ms RMS frames against the clip's own noise floor.

    A held turn has its long pauses cut from the audio by the VAD, so when the turn's
    timeline span is known, pause time is ``span_s - speaking_s``. Pauses over 1 s and the
    longest pause are measured inside the clip. Returns None if the file can't be read.
    """
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            raw = w.readframes(w.getnframes())
        if width != 2 or rate <= 0:
            return None
        x = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float64) / 32768.0
        if ch > 1:
            x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    except (OSError, EOFError, wave.Error):
        return None
    n = int(rate * FRAME_S)
    frames = len(x) // n
    if frames == 0:
        return None
    rms = np.sqrt((x[: frames * n].reshape(frames, n) ** 2).mean(axis=1))
    floor = float(np.percentile(rms, 10))
    voiced = rms > max(floor * 3.0, 0.01)
    idx = np.flatnonzero(voiced)
    if idx.size == 0:
        return {"speaking_s": 0.0, "pause_s": round(max(span_s or 0.0, 0.0), 2), "pauses_over_1s": 0, "longest_pause_s": 0.0}
    # Silent runs between the first and last voiced frame; short dips count as speech.
    gaps = np.diff(idx) - 1
    for k in np.flatnonzero(gaps < _BRIDGE_FRAMES):
        voiced[idx[k] : idx[k + 1]] = True
    speaking = float(voiced.sum()) * FRAME_S
    pauses = [g * FRAME_S for g in gaps if g >= _BRIDGE_FRAMES]
    pause_s = max(span_s - speaking, 0.0) if span_s else float(sum(pauses))
    return {
        "speaking_s": round(speaking, 2),
        "pause_s": round(pause_s, 2),
        "pauses_over_1s": sum(1 for p in pauses if p >= 1.0),
        "longest_pause_s": round(max(pauses, default=0.0), 2),
    }


def _turn_seconds(t: dict) -> float:
    a, b = t.get("t_start_ms"), t.get("t_end_ms")
    if a is not None and b is not None and b > a:
        return (b - a) / 1000
    return len(t["text"].split()) / 2.5


def answer_delivery(answers: list[dict], turns: list[dict], audio_dir=None) -> None:
    """Add a ``delivery`` object to each answer (in place).

    An answer covers the candidate turns after its ``question_turn`` and before the next
    answer's (the answer plus its follow-ups). ``audio_dir`` holds ``<turn_idx>.wav``;
    with no audio, ``pauses_over_1s`` stays None.
    """
    starts = sorted(a["question_turn"] for a in answers if isinstance(a.get("question_turn"), int))
    for a in answers:
        qt = a.get("question_turn")
        if not isinstance(qt, int):
            continue
        nxt = next((s for s in starts if s > qt), None)
        mine = [t for t in turns if t["speaker"] == "candidate" and t["idx"] > qt and (nxt is None or t["idx"] < nxt)]
        if not mine:
            continue
        stats = [text_stats(t["text"]) for t in mine]
        total = lambda k: sum(s[k] for s in stats)  # noqa: E731
        seconds = sum(_turn_seconds(t) for t in mine)
        first = _turn_seconds(mine[0])
        pauses = None
        if audio_dir is not None:
            for t in mine:
                span = _turn_seconds(t) if t.get("t_start_ms") is not None and t.get("t_end_ms") is not None else None
                st = audio_stats(Path(audio_dir) / f"{t['idx']}.wav", span)
                if st:
                    pauses = (pauses or 0) + st["pauses_over_1s"]
        target = TARGET_SECONDS.get(a.get("category"))
        flag = None
        if target:
            flag = "short" if first < target[0] else "long" if first > target[1] else None
        a["delivery"] = {
            "seconds": round(seconds, 1),
            "first_answer_seconds": round(first, 1),
            "wpm": round(total("words") / seconds * 60) if seconds > 0 else None,
            "fillers": total("fillers"),
            "hedges": total("hedges"),
            "i_count": total("i_count"),
            "we_count": total("we_count"),
            "numbers": total("numbers"),
            "pauses_over_1s": pauses,
            "target": list(target) if target else None,
            "flag": flag,
        }


def _mmss(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def delivery_line(d: dict | None) -> str:
    """One-line summary, e.g. ``1:12 (aim 1:00-1:30) · 138 wpm · I 6 / we 2 · 3 numbers · 2 fillers · 1 hedge``."""
    if not d:
        return ""
    t = _mmss(d["first_answer_seconds"])
    if d.get("target"):
        t += f" (aim {_mmss(d['target'][0])}-{_mmss(d['target'][1])})"
    plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")  # noqa: E731
    parts = [t]
    if d.get("wpm"):
        parts.append(f"{d['wpm']} wpm")
    parts += [f"I {d['i_count']} / we {d['we_count']}", plural(d["numbers"], "number"), plural(d["fillers"], "filler"), plural(d["hedges"], "hedge")]
    if d.get("pauses_over_1s"):
        parts.append(plural(d["pauses_over_1s"], "long pause"))
    return " · ".join(parts)
