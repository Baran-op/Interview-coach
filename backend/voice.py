"""Voice analysis beyond the per-answer numbers (PLAN-voice.md): time mapping, flat sections, evidence.

Pure functions over the output of ``delivery.pitch_track`` and a turn's speech ``segments``.
The answer WAV of one candidate turn is that turn's VAD speech segments joined, so a WAV time maps to
a session-clock time by the lengths of the segments before it. Times are milliseconds.
"""

from __future__ import annotations


def _spans(segments) -> list[tuple[float, float, float]]:
    """(start, end, wav offset of the start) per segment, in order; empty for no usable segments."""
    out, offset = [], 0.0
    for s in segments or []:
        a, b = float(s["start_ms"]), float(s["end_ms"])
        if b <= a:
            continue
        out.append((a, b, offset))
        offset += b - a
    return out


def wav_to_session(ms: float, segments) -> float | None:
    """Session-clock time of a WAV time. Past the end snaps to the last segment's end, before 0 to the first start.
    None when there are no segments (the caller falls back to WAV time)."""
    spans = _spans(segments)
    if not spans:
        return None
    ms = max(float(ms), 0.0)
    for a, b, off in spans:
        if ms <= off + (b - a):
            return a + (ms - off)
    return spans[-1][1]


def session_to_wav(ms: float, segments) -> float | None:
    """WAV time of a session-clock time. A time inside a cut gap (or outside all segments) snaps to the
    nearest segment edge, the earlier edge on a tie. None when there are no segments."""
    spans = _spans(segments)
    if not spans:
        return None
    ms = float(ms)
    best, best_d = 0.0, None
    for a, b, off in spans:
        if a <= ms <= b:
            return off + (ms - a)
        for edge, wav in ((a, off), (b, off + (b - a))):
            d = abs(ms - edge)
            if best_d is None or d < best_d:
                best, best_d = wav, d
    return best


def joins(segments) -> list[dict]:
    """Where silence was cut between segments: ``[{wav_ms, cut_ms}]`` (WAV time of the join, length of the cut)."""
    spans = _spans(segments)
    out = []
    for (a0, b0, off0), (a1, _b1, off1) in zip(spans, spans[1:]):
        if a1 > b0:
            out.append({"wav_ms": off1, "cut_ms": a1 - b0})
    return out
