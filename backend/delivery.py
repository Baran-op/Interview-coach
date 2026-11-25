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


def read_wav(wav_path) -> tuple[np.ndarray, int] | None:
    """Mono float samples in [-1, 1] and the sample rate of a 16-bit WAV, or None if unreadable."""
    try:
        with wave.open(str(wav_path), "rb") as w:
            rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            raw = w.readframes(w.getnframes())
        if width != 2 or rate <= 0:
            return None
        x = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float64) / 32768.0
        if ch > 1:
            x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
        return x, rate
    except (OSError, EOFError, wave.Error):
        return None


def voiced_frames(x: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray] | None:
    """30 ms RMS per frame and the voiced mask (RMS over 3x the clip's 10th percentile and 0.01)."""
    n = int(rate * FRAME_S)
    frames = len(x) // n if n > 0 else 0
    if frames == 0:
        return None
    rms = np.sqrt((x[: frames * n].reshape(frames, n) ** 2).mean(axis=1))
    floor = float(np.percentile(rms, 10))
    return rms, rms > max(floor * 3.0, 0.01)


def _bridge(voiced: np.ndarray):
    """Fill dips shorter than ``_BRIDGE_FRAMES`` in place; returns (voiced indices, silent run lengths between them)."""
    idx = np.flatnonzero(voiced)
    gaps = np.diff(idx) - 1
    for k in np.flatnonzero(gaps < _BRIDGE_FRAMES):
        voiced[idx[k] : idx[k + 1]] = True
    return idx, gaps


def audio_stats(wav_path, span_s: float | None = None) -> dict | None:
    """Speaking and pause time from 30 ms RMS frames against the clip's own noise floor.

    A held turn has its long pauses cut from the audio by the VAD, so when the turn's
    timeline span is known, pause time is ``span_s - speaking_s``. Pauses over 1 s and the
    longest pause are measured inside the clip. Returns None if the file can't be read.
    """
    wav = read_wav(wav_path)
    if wav is None:
        return None
    vf = voiced_frames(*wav)
    if vf is None:
        return None
    voiced = vf[1]
    idx, gaps = _bridge(voiced)
    if idx.size == 0:
        return {"speaking_s": 0.0, "pause_s": round(max(span_s or 0.0, 0.0), 2), "pauses_over_1s": 0, "longest_pause_s": 0.0}
    speaking = float(voiced.sum()) * FRAME_S
    pauses = [g * FRAME_S for g in gaps if g >= _BRIDGE_FRAMES]
    pause_s = max(span_s - speaking, 0.0) if span_s else float(sum(pauses))
    return {
        "speaking_s": round(speaking, 2),
        "pause_s": round(pause_s, 2),
        "pauses_over_1s": sum(1 for p in pauses if p >= 1.0),
        "longest_pause_s": round(max(pauses, default=0.0), 2),
    }


MIN_VOICED_S = 8.0
_F0_MIN, _F0_MAX = 70.0, 400.0
_YIN_THRESHOLD = 0.15  # cumulative mean normalised difference below this = clearly periodic
_PHRASE_GAP_FRAMES = 9  # 250 ms or more splits phrases
_PHRASE_MIN_FRAMES = 34  # phrases of 1 s or longer
_TAIL_FRAMES = 10  # the last 300 ms
_TRAIL_DB = 6.0


def _f0(frame: np.ndarray, rate: int) -> float | None:
    """YIN-style f0 of one frame (``frame`` holds window + max lag samples), or None if not clearly periodic."""
    tau_min, tau_max = int(rate / _F0_MAX), int(rate / _F0_MIN)
    w = len(frame) - tau_max
    if w <= tau_max // 2:
        return None
    size = 1 << (len(frame) + w).bit_length()
    acf = np.fft.irfft(np.fft.rfft(frame, size) * np.conj(np.fft.rfft(frame[:w], size)), size)[: tau_max + 1]
    e = np.concatenate(([0.0], np.cumsum(frame**2)))
    taus = np.arange(tau_max + 1)
    d = e[w] + (e[taus + w] - e[taus]) - 2 * acf
    d[0] = 0.0
    cm = np.ones(tau_max + 1)
    csum = np.cumsum(d[1:])
    cm[1:] = d[1:] * taus[1:] / np.maximum(csum, 1e-12)
    below = np.flatnonzero(cm[tau_min:tau_max] < _YIN_THRESHOLD)
    if below.size == 0:
        return None
    t = tau_min + int(below[0])
    while t + 1 < tau_max and cm[t + 1] < cm[t]:  # walk down to the local minimum
        t += 1
    a, b, c = cm[t - 1], cm[t], cm[t + 1]
    denom = a - 2 * b + c
    shift = 0.5 * (a - c) / denom if denom > 1e-12 else 0.0
    return rate / (t + float(np.clip(shift, -1, 1)))


def _pitch_range_st(x: np.ndarray, rate: int, voiced: np.ndarray) -> float | None:
    n = int(rate * FRAME_S)
    lag = int(rate / _F0_MIN)
    f0s = []
    for i in np.flatnonzero(voiced):
        seg = x[i * n : i * n + n + lag]
        if len(seg) < n + lag:
            continue
        f = _f0(seg, rate)
        if f:
            f0s.append(f)
    if len(f0s) < 10:
        return None
    st = 12 * np.log2(np.array(f0s) / float(np.median(f0s)))
    st = np.where(st > 9, st - 12, np.where(st < -9, st + 12, st))  # octave errors fold back
    st = st[np.abs(st) <= 12]
    if len(st) < 10:
        return None
    return float(np.percentile(st, 90) - np.percentile(st, 10))


def voice_stats(samples, rate: int) -> dict | None:
    """Pitch range, loudness range, trailing off and speaking time from mono float samples.

    ``pitch_range_st`` and ``loudness_range_db`` are 10th-90th percentile spreads (semitones, dB);
    ``trail_off_pct`` is the share of phrases (1 s+, split at 250 ms gaps) whose last 300 ms is 6 dB
    or more under the rest. None below 8 s of voiced speech. ``pitch_range_st`` and ``trail_off_pct``
    can be None when there's nothing to measure.
    """
    x = np.asarray(samples, dtype=np.float64)
    vf = voiced_frames(x, rate)
    if vf is None:
        return None
    rms, raw = vf
    voiced = raw.copy()
    idx, _ = _bridge(voiced)
    voiced_s = float(voiced.sum()) * FRAME_S
    if idx.size == 0 or voiced_s < MIN_VOICED_S:
        return None
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    lv = db[raw]
    loud = float(np.percentile(lv, 90) - np.percentile(lv, 10))
    # phrases: runs of voiced frames, joined across gaps shorter than 250 ms
    runs: list[list[int]] = []
    for i in np.flatnonzero(voiced):
        if runs and i - runs[-1][1] - 1 < _PHRASE_GAP_FRAMES:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    trail = []
    for a, b in runs:
        if b - a + 1 < _PHRASE_MIN_FRAMES:
            continue
        seg = rms[a : b + 1]
        tail = 20 * np.log10(max(float(np.sqrt((seg[-_TAIL_FRAMES:] ** 2).mean())), 1e-6))
        rest = float(np.median(db[a : b + 1 - _TAIL_FRAMES]))
        trail.append(tail <= rest - _TRAIL_DB)
    pitch = _pitch_range_st(x, rate, raw)
    return {
        "pitch_range_st": round(pitch, 2) if pitch is not None else None,
        "loudness_range_db": round(loud, 1),
        "trail_off_pct": round(100 * sum(trail) / len(trail)) if trail else None,
        "voiced_s": round(voiced_s, 1),
    }


VOICE_KEYS = ("pitch_range_st", "loudness_range_db", "trail_off_pct")
_FLAT_NO_BASELINE_ST = 4.0
VOICE_FLAG_LABEL = {"flat": "flat", "lively": "lively", "trailing": "trailing off"}


def voice_flags(voice: dict | None, baseline: dict | None) -> list[str]:
    """Flags for one answer's voice stats: ``flat``, ``lively`` and ``trailing`` (PLAN-energy.md, 1c).

    With a baseline (your usual numbers) flat is under 0.75 x usual pitch range and lively over 1.25 x;
    without one flat is under 4 st and lively never applies. Trailing is a trail-off share of 40% or more,
    and also 15 points over your usual when there is one. Missing numbers raise no flag.
    """
    if not voice:
        return []
    base = baseline or {}
    flags = []
    pitch, usual = voice.get("pitch_range_st"), base.get("pitch_range_st")
    if pitch is not None:
        if usual:
            if pitch < 0.75 * usual:
                flags.append("flat")
            elif pitch > 1.25 * usual:
                flags.append("lively")
        elif pitch < _FLAT_NO_BASELINE_ST:
            flags.append("flat")
    trail, usual_trail = voice.get("trail_off_pct"), base.get("trail_off_pct")
    if trail is not None and trail >= 40 and (usual_trail is None or trail - usual_trail >= 15):
        flags.append("trailing")
    return flags


def voice_fields(voice: dict | None, baseline: dict | None) -> dict:
    """The three voice keys stored in a ``delivery`` object."""
    return {
        "voice": voice,
        "voice_flags": voice_flags(voice, baseline),
        "voice_usual": {k: baseline.get(k) for k in VOICE_KEYS} if baseline and voice else None,
    }


def voice_from_wavs(paths) -> dict | None:
    """Voice stats over the readable WAVs joined together (one answer = its turns' samples), or None."""
    parts, rate = [], None
    for p in paths:
        wav = read_wav(p)
        if wav is None or (rate is not None and wav[1] != rate):
            continue
        parts.append(wav[0])
        rate = wav[1]
    if not parts:
        return None
    return voice_stats(np.concatenate(parts), rate)


FACE_FLAG_LABEL = {"looking_down": "mostly looking down", "low_eye_contact": "low eye contact", "still": "still face"}
FACE_MOMENT_LABEL = {"down": "Looked down", "away": "Looked away", "still": "Still face"}
_STILL_WINDOW_MS = 5000
_STILL_MIN_MS = 20_000
_FACE_MIN_FOUND_PCT = 50


def combine_face(faces: list[dict | None]) -> dict | None:
    """One answer's face stats from its turns' stored face objects, each percentage weighted by frames.

    Turns whose stat is null (face found in under half the frames) are left out of that stat. Spans and
    windows are joined in time order. None when no turn has face data.
    """
    faces = [f for f in faces if isinstance(f, dict)]
    if not faces:
        return None
    frames = sum(f.get("frames") or 0 for f in faces)

    def wavg(key: str) -> float | None:
        pairs = [(f[key], f.get("frames") or 0) for f in faces if f.get(key) is not None]
        if not pairs:
            return None
        w = sum(n for _, n in pairs)
        return sum(v * n for v, n in pairs) / w if w else sum(v for v, _ in pairs) / len(pairs)

    found = wavg("face_found_pct")
    ok = found is not None and found >= _FACE_MIN_FOUND_PCT
    stat = lambda k, nd: (round(v, nd) if (v := wavg(k)) is not None and ok else None)  # noqa: E731
    return {
        "t_start_ms": min(f.get("t_start_ms", 0) for f in faces),
        "t_end_ms": max(f.get("t_end_ms", 0) for f in faces),
        "on_screen_pct": stat("on_screen_pct", 1),
        "looked_down_pct": stat("looked_down_pct", 1),
        "expressiveness": stat("expressiveness", 2),
        "face_found_pct": round(found, 1) if found is not None else None,
        "frames": frames,
        "away_spans": sorted((s for f in faces for s in f.get("away_spans") or []), key=lambda s: s["start_ms"]),
        "expr_windows": sorted((w for f in faces for w in f.get("expr_windows") or []), key=lambda w: w["start_ms"]),
    }


def face_flags(face: dict | None, baseline: dict | None) -> list[str]:
    """Flags for one answer's face stats (PLAN-energy.md, 2b).

    ``looking_down``: looked down 30% or more. ``low_eye_contact``: on screen under 60%. ``still``:
    expressiveness under 0.7 x your usual, and only once there is a baseline. Null numbers raise no flag.
    """
    if not face:
        return []
    flags = []
    down, on = face.get("looked_down_pct"), face.get("on_screen_pct")
    if down is not None and down >= 30:
        flags.append("looking_down")
    if on is not None and on < 60:
        flags.append("low_eye_contact")
    expr, usual = face.get("expressiveness"), (baseline or {}).get("expressiveness")
    if expr is not None and usual and expr < 0.7 * usual:
        flags.append("still")
    return flags


def face_moments(face: dict | None, baseline: dict | None) -> list[dict]:
    """Where it went wrong: the away spans, plus still stretches (``kind: "still"``).

    A still stretch is 20 s or more of consecutive 5 s expression windows each under half your usual
    expressiveness. With no baseline there are none. Sorted by start time; times are on the session clock.
    """
    if not face:
        return []
    out = [{"kind": s["kind"], "start_ms": s["start_ms"], "end_ms": s["end_ms"]}
           for s in face.get("away_spans") or [] if s.get("kind") in ("down", "away")]
    usual = (baseline or {}).get("expressiveness")
    if usual:
        run: list[dict] = []

        def close():
            if run and run[-1]["start_ms"] + _STILL_WINDOW_MS - run[0]["start_ms"] >= _STILL_MIN_MS:
                end = run[-1]["start_ms"] + _STILL_WINDOW_MS
                if face.get("t_end_ms") is not None:
                    end = min(end, max(face["t_end_ms"], run[0]["start_ms"] + 1))
                out.append({"kind": "still", "start_ms": run[0]["start_ms"], "end_ms": end})

        for w in sorted(face.get("expr_windows") or [], key=lambda w: w["start_ms"]):
            if w["value"] < 0.5 * usual:
                if run and w["start_ms"] - run[-1]["start_ms"] != _STILL_WINDOW_MS:
                    close()
                    run = []
                run.append(w)
            else:
                close()
                run = []
        close()
    return sorted(out, key=lambda m: m["start_ms"])


QUOTE_WORDS = 15


def _words_in(turn: dict, start_ms: float, end_ms: float) -> list[str]:
    """The words of one turn spoken between two session-clock times, found through the turn's segments.

    The answer WAV is the kept speech segments joined, so a session time maps to a WAV offset by the
    lengths of the segments before it. A word counts when its midpoint falls inside the span.
    """
    segs, words = turn.get("segments") or [], turn.get("words") or []
    if not segs or not words:
        return []
    ranges, offset = [], 0
    for s in segs:
        a, b = max(start_ms, s["start_ms"]), min(end_ms, s["end_ms"])
        if b > a:
            lo = offset + a - s["start_ms"]
            ranges.append((lo, lo + (b - a)))
        offset += s["end_ms"] - s["start_ms"]
    out = []
    for w in words:
        mid = (w["start_ms"] + w["end_ms"]) / 2
        if any(lo <= mid < hi for lo, hi in ranges):
            out.append(w["w"])
    return out


def _quote(words: list[str]) -> str | None:
    if not words:
        return None
    return " ".join(words[:QUOTE_WORDS]) + ("…" if len(words) > QUOTE_WORDS else "")


def words_at(turn: dict, start_ms: float, end_ms: float) -> str | None:
    """What you were saying in a span of the session clock, about 15 words then an ellipsis. None when the
    turn has no segments or no words (typed answers, older sessions) or nothing was said in the span."""
    return _quote(_words_in(turn, start_ms, end_ms))


def moment_quote(turns: list[dict], start_ms: float, end_ms: float) -> str | None:
    """`words_at` across all of an answer's turns, capped once."""
    return _quote([w for t in turns for w in _words_in(t, start_ms, end_ms)])


def add_quotes(face_delivery: dict, turns: list[dict]) -> dict:
    """Put a ``quote`` on each moment of a ``face_fields`` result (in place; returns it)."""
    for m in (face_delivery.get("face") or {}).get("moments") or []:
        q = moment_quote(turns, m["start_ms"], m["end_ms"])
        if q:
            m["quote"] = q
    return face_delivery


def face_moment_text(m: dict) -> str:
    """``Looked down 0:42-0:51 (9 s)``, or ``Still face 2:10-2:38 (28 s)`` (with an en dash)."""
    secs = max(0, round((m["end_ms"] - m["start_ms"]) / 1000))
    return f"{FACE_MOMENT_LABEL.get(m['kind'], m['kind'])} {_mmss(m['start_ms'] / 1000)}\u2013{_mmss(m['end_ms'] / 1000)} ({secs} s)"


def face_fields(face: dict | None, baseline: dict | None) -> dict:
    """The face keys stored in a ``delivery`` object. ``face.moments`` is rebuilt from the spans and windows."""
    if not face:
        return {"face": None, "face_flags": [], "face_usual": None}
    face = {**{k: v for k, v in face.items() if k != "moments"}, "moments": face_moments(face, baseline)}
    return {
        "face": face,
        "face_flags": face_flags(face, baseline),
        "face_usual": {"expressiveness": baseline.get("expressiveness")} if baseline and face.get("expressiveness") is not None else None,
    }


def _turn_seconds(t: dict) -> float:
    a, b = t.get("t_start_ms"), t.get("t_end_ms")
    if a is not None and b is not None and b > a:
        return (b - a) / 1000
    return len(t["text"].split()) / 2.5


def answer_turns(answer: dict, answers: list[dict], turns: list[dict]) -> list[dict]:
    """The candidate turns that make up one answer: after its question turn, before the next answer's."""
    qt = answer.get("question_turn")
    if not isinstance(qt, int):
        return []
    nxt = next((s for s in sorted(a["question_turn"] for a in answers if isinstance(a.get("question_turn"), int)) if s > qt), None)
    return [t for t in turns if t["speaker"] == "candidate" and t["idx"] > qt and (nxt is None or t["idx"] < nxt)]


def answer_delivery(answers: list[dict], turns: list[dict], audio_dir=None, voice_baseline: dict | None = None,
                    face_baseline: dict | None = None) -> None:
    """Add a ``delivery`` object to each answer (in place).

    An answer covers the candidate turns after its ``question_turn`` and before the next
    answer's (the answer plus its follow-ups). ``audio_dir`` holds ``<turn_idx>.wav``;
    with no audio, ``pauses_over_1s`` stays None and ``voice`` is None. ``voice_baseline`` is
    ``db.voice_baseline()``: your usual voice numbers, used for the voice flags.
    ``face_baseline`` is ``db.face_baseline()``; each answer's turns' ``face`` stats are combined into ``delivery.face``.
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
        voice = None
        if audio_dir is not None:
            voice = voice_from_wavs(Path(audio_dir) / f"{t['idx']}.wav" for t in mine)
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
            **voice_fields(voice, voice_baseline),
            **add_quotes(face_fields(combine_face([t.get("face") for t in mine]), face_baseline), mine),
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
    flags = [VOICE_FLAG_LABEL[f] for f in d.get("voice_flags") or [] if f in VOICE_FLAG_LABEL]
    if flags:
        parts.append("voice: " + ", ".join(flags))
    face = d.get("face")
    if face and face.get("on_screen_pct") is not None:
        parts.append(f"eye contact {round(face['on_screen_pct'])}%")
    parts += [FACE_FLAG_LABEL[f] for f in d.get("face_flags") or [] if f in FACE_FLAG_LABEL and f != "low_eye_contact"]
    return " · ".join(parts)
