"""Validation of the speech segments the browser posts with an answer (times only, never audio)."""

import json
import math

MAX_RAW_BYTES = 32_000
MAX_SEGMENTS = 200
MAX_TOTAL_MS = 15 * 60 * 1000


def clean_segments(raw, max_ms: int) -> list[dict] | None:
    """``[{start_ms, end_ms}]`` on the session clock, one per speech segment kept in the answer's WAV, in order.

    The WAV is those segments joined, so a segment's length is also its length in the WAV. Segments must be
    finite, inside ``0..max_ms``, in time order and not overlapping; bad ones are dropped, the list is capped
    and its total length limited. Returns None when nothing usable was sent.
    """
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_RAW_BYTES:
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, list):
        return None
    max_ms = max(0, int(max_ms))
    out: list[dict] = []
    last_end = 0
    total = 0
    for s in raw:
        if len(out) >= MAX_SEGMENTS:
            break
        if not isinstance(s, dict):
            continue
        a, b = s.get("start_ms"), s.get("end_ms")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (a, b)):
            continue
        a, b = int(a), int(b)
        if a < last_end or b <= a or b > max_ms or total + (b - a) > MAX_TOTAL_MS:
            continue
        out.append({"start_ms": a, "end_ms": b})
        last_end, total = b, total + (b - a)
    return out or None
