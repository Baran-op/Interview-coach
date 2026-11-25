"""Validation of the per-answer face stats the browser posts with an answer (numbers only, never video)."""

import json
import math

MAX_RAW_BYTES = 64_000
MAX_SPANS = 20
MAX_WINDOWS = 120  # 5 s windows: 10 minutes
SPAN_KINDS = ("down", "away")
PCT_KEYS = ("on_screen_pct", "looked_down_pct", "face_found_pct")
MAX_EXPRESSIVENESS = 100.0
MAX_FRAMES = 20_000


def _num(v, lo: float, hi: float) -> float | None:
    """A finite number clamped to [lo, hi], else None (booleans are not numbers)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return min(hi, max(lo, float(v)))


def clean_face(raw, max_ms: int) -> dict | None:
    """Keep only known keys, clamp the numbers and keep spans inside the answer's time range.

    `raw` is the posted JSON (string, dict or None). `max_ms` is the latest time on the session clock
    that can exist yet (the session's elapsed time). Returns None when nothing usable was sent.
    """
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_RAW_BYTES:
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    max_ms = max(0, int(max_ms))
    t0 = _num(raw.get("t_start_ms"), 0, max_ms)
    t1 = _num(raw.get("t_end_ms"), 0, max_ms)
    if t0 is None or t1 is None or t1 < t0:
        return None
    t0, t1 = int(t0), int(t1)

    out: dict = {"t_start_ms": t0, "t_end_ms": t1}
    frames = _num(raw.get("frames"), 0, MAX_FRAMES)
    out["frames"] = int(frames) if frames is not None else 0
    for key in PCT_KEYS:
        v = _num(raw.get(key), 0, 100)
        out[key] = round(v, 1) if v is not None else None
    expr = _num(raw.get("expressiveness"), 0, MAX_EXPRESSIVENESS)
    out["expressiveness"] = round(expr, 2) if expr is not None else None

    spans = []
    for s in raw.get("away_spans") or []:
        if len(spans) >= MAX_SPANS:
            break
        if not isinstance(s, dict) or s.get("kind") not in SPAN_KINDS:
            continue
        a, b = _num(s.get("start_ms"), t0, t1), _num(s.get("end_ms"), t0, t1)
        if a is None or b is None or b <= a:
            continue
        spans.append({"start_ms": int(a), "end_ms": int(b), "kind": s["kind"]})
    out["away_spans"] = sorted(spans, key=lambda s: s["start_ms"])

    windows = []
    for w in raw.get("expr_windows") or []:
        if len(windows) >= MAX_WINDOWS:
            break
        if not isinstance(w, dict):
            continue
        a, v = _num(w.get("start_ms"), t0, t1), _num(w.get("value"), 0, MAX_EXPRESSIVENESS)
        if a is None or v is None:
            continue
        windows.append({"start_ms": int(a), "value": round(v, 2)})
    out["expr_windows"] = windows
    return out
