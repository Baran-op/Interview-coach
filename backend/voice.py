"""Voice analysis beyond the per-answer numbers (PLAN-voice.md): time mapping, flat sections, evidence.

Pure functions over the output of ``delivery.pitch_track`` and a turn's speech ``segments``.
The answer WAV of one candidate turn is that turn's VAD speech segments joined, so a WAV time maps to
a session-clock time by the lengths of the segments before it. Times are milliseconds.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("interview-coach.voice")


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


# --------------------------------------------------------------- flat sections (V2) --- #
# Every constant in this block is PROVISIONAL until V3's calibration (scripts/voice_windows.py plus your
# listening) sets the real values. Nothing here is a verdict yet; the UI labels sections "provisional".
import numpy as np  # noqa: E402

from . import delivery  # noqa: E402

THRESHOLDS_PROVISIONAL = True
WINDOW_FRAMES = 333  # 10 s of WAV time
HOP_FRAMES = 83  # 2.5 s
MIN_PITCHED = 60  # pitched frames (1.8 s) a window needs to be measured; PROVISIONAL
FLAT_RELATIVE = 0.6  # flat: window spread under this x your usual window spread; PROVISIONAL
FLAT_ABSOLUTE_ST = 2.5  # flat with no baseline: window spread under this many semitones; PROVISIONAL
LONG_CUT_MS = 2000  # a window never straddles a join whose cut pause was at least this long
MIN_TURN_S = 12.0  # no sections under this much WAV time ...
MIN_TURN_VOICED_S = delivery.MIN_VOICED_S  # ... or this much voiced speech
MAX_PER_TURN = 2  # sections per turn that may get advice (flattest first)
MAX_PER_SESSION = 6  # and per session


def _runs(n_frames: int, join_list) -> list[tuple[int, int]]:
    """Frame ranges ``[a, b)`` that windows may cover: the track split after each long-cut join."""
    cuts = sorted({int(round(j["wav_ms"] / delivery.FRAME_S / 1000)) for j in join_list or [] if j.get("cut_ms", 0) >= LONG_CUT_MS})
    edges = [0, *[c for c in cuts if 0 < c < n_frames], n_frames]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def _centre(track: dict, center_hz: float | None) -> float | None:
    f0 = track["f0_hz"][~np.isnan(track["f0_hz"])]
    if center_hz:
        return float(center_hz)
    return float(np.median(f0)) if len(f0) else None


def window_spreads(track: dict, join_list=None, center_hz: float | None = None) -> list[dict]:
    """Every measurable 10 s window of a pitch track: ``[{a, b, spread_st, pitched}]`` (frame range ``[a, b)``).

    Spread is the 10th-90th percentile of the window's pitched frames in semitones from the turn's median f0
    (or ``center_hz``), the definition of ``pitch_range_st``. Windows with under ``MIN_PITCHED`` pitched frames
    are left out. Windows restart after a join that cut 2 s or more, and a last window is aligned to each
    run's end. Nothing is returned for a turn under ``MIN_TURN_S`` or ``MIN_TURN_VOICED_S``.
    """
    f0 = track["f0_hz"]
    n = len(f0)
    if n * delivery.FRAME_S < MIN_TURN_S:
        return []
    voiced = track["voiced"].copy()
    delivery._bridge(voiced)
    if voiced.sum() * delivery.FRAME_S < MIN_TURN_VOICED_S:
        return []
    c = _centre(track, center_hz)
    if c is None:
        return []
    st = delivery.to_semitones(f0, c)
    out = []
    for ra, rb in _runs(n, join_list):
        if rb - ra < WINDOW_FRAMES:
            continue
        starts = list(range(ra, rb - WINDOW_FRAMES + 1, HOP_FRAMES))
        if starts[-1] + WINDOW_FRAMES < rb:
            starts.append(rb - WINDOW_FRAMES)
        for a in starts:
            w = st[a : a + WINDOW_FRAMES]
            w = w[~np.isnan(w)]
            if len(w) >= MIN_PITCHED:
                out.append({"a": a, "b": a + WINDOW_FRAMES, "spread_st": float(np.percentile(w, 90) - np.percentile(w, 10)),
                            "pitched": int(len(w))})
    return out


def flat_threshold(baseline: dict | None) -> float:
    """Window spread under which a window is flat: ``FLAT_RELATIVE`` x your usual window spread, else ``FLAT_ABSOLUTE_ST``."""
    usual = (baseline or {}).get("window_range_st")
    return FLAT_RELATIVE * usual if usual else FLAT_ABSOLUTE_ST


def _snap_to_words(a_ms: float, b_ms: float, words) -> tuple[float, float]:
    if not words:
        return a_ms, b_ms
    first = next((w for w in words if w["end_ms"] > a_ms), None)
    last = next((w for w in reversed(words) if w["start_ms"] < b_ms), None)
    if first is None or last is None or last["end_ms"] <= first["start_ms"]:
        return a_ms, b_ms
    return float(first["start_ms"]), float(last["end_ms"])


def flat_sections(track: dict | None, joins_list=None, baseline: dict | None = None, turn_idx: int = 0,
                  words=None, center_hz: float | None = None) -> list[dict]:
    """Flat stretches of one turn: ``[{id, start_ms, end_ms, range_st, pitched_s, advice_ok}]`` in WAV time.

    Consecutive overlapping flat windows (see ``window_spreads``, ``flat_threshold``) merge into one section;
    its edges are trimmed to the first and last pitched frame and then snapped to word edges when ``words``
    ([{w, start_ms, end_ms}]) exist. ``range_st`` is re-measured over the whole section. IDs are
    ``T<turn_idx>.<n>`` in time order. ``advice_ok`` is True for the ``MAX_PER_TURN`` flattest sections;
    the rest are drawn but get no advice. PROVISIONAL thresholds (see the constants).
    """
    if not track:
        return []
    thr = flat_threshold(baseline)
    wins = [w for w in window_spreads(track, joins_list, center_hz) if w["spread_st"] < thr]
    if not wins:
        return []
    c = _centre(track, center_hz)
    st = delivery.to_semitones(track["f0_hz"], c)
    groups: list[list[dict]] = []
    for w in wins:
        if groups and w["a"] < groups[-1][-1]["b"] and w["a"] - groups[-1][-1]["a"] <= HOP_FRAMES:
            groups[-1].append(w)
        else:
            groups.append([w])
    fm = delivery.FRAME_S * 1000
    out = []
    for g in groups:
        a, b = g[0]["a"], g[-1]["b"]
        idx = np.flatnonzero(~np.isnan(st[a:b]))
        if len(idx) == 0:
            continue
        lo, hi = a + int(idx[0]), a + int(idx[-1]) + 1
        vals = st[lo:hi][~np.isnan(st[lo:hi])]
        start_ms, end_ms = _snap_to_words(lo * fm, hi * fm, words)
        out.append({
            "start_ms": int(round(start_ms)), "end_ms": int(round(end_ms)),
            "range_st": round(float(np.percentile(vals, 90) - np.percentile(vals, 10)), 2),
            "pitched_s": round(len(vals) * delivery.FRAME_S, 1),
        })
    for rank, s in enumerate(sorted(out, key=lambda s: (s["range_st"], s["start_ms"]))):
        s["advice_ok"] = rank < MAX_PER_TURN
    out.sort(key=lambda s: s["start_ms"])
    return [{"id": f"T{turn_idx}.{i}", **s} for i, s in enumerate(out, 1)]


def cap_session(sections: list[dict], limit: int = MAX_PER_SESSION) -> list[dict]:
    """Of a session's sections (all turns), only the ``limit`` flattest keep ``advice_ok`` (in place; returns the list)."""
    keep = {s["id"] for s in sorted((s for s in sections if s.get("advice_ok")), key=lambda s: (s["range_st"], s["id"]))[:limit]}
    for s in sections:
        s["advice_ok"] = s["id"] in keep
    return sections


# ------------------------------------------------------- evidence for the report (V6) --- #

MAX_QUOTE_WORDS = 40  # words of a flat stretch sent to Claude and stored
_MAX_TEXT = 300  # say_it and why
_STATE_RE = re.compile(
    r"\b(?:confiden\w*|nervous\w*|anxi\w*|bored\w*|boring|unsure|shy|enthusias\w*|passion\w*|excite\w*|insecur\w*|timid\w*)",
    re.IGNORECASE,
)


def words_in(words, start_ms: float, end_ms: float, limit: int | None = MAX_QUOTE_WORDS) -> list[str]:
    """The words whose midpoint falls inside a WAV-time span (the exact words of a stretch), at most ``limit``."""
    out = [w["w"] for w in words or [] if start_ms <= (w["start_ms"] + w["end_ms"]) / 2 < end_ms]
    return out if limit is None else out[:limit]


def _fmt_time(ms: float) -> str:
    return delivery._mmss(ms / 1000)


def turn_evidence(turns: list[dict], audio_dir, baseline: dict | None = None) -> dict[int, dict]:
    """Voice evidence per spoken candidate turn, computed locally before the report request.

    ``{turn_idx: {"stats": voice_stats | None, "flags": [...], "usual": baseline pitch range | None,
    "sections": [section]}}`` for every candidate turn whose ``<idx>.wav`` is readable. A section is
    ``{id, turn_idx, start_ms, end_ms (WAV time), session_start_ms, session_end_ms (None without segments),
    range_st, pitched_s, advice_ok, provisional, words}``. The ``MAX_PER_SESSION`` flattest sections (and at
    most ``MAX_PER_TURN`` per turn) have ``advice_ok``: only those go to Claude. Never raises on bad audio.
    """
    out: dict[int, dict] = {}
    all_sections: list[dict] = []
    for t in turns:
        if t.get("speaker") != "candidate":
            continue
        try:
            wav = delivery.read_wav(Path(audio_dir) / f"{t['idx']}.wav")
            if wav is None:
                continue
            track = delivery.pitch_track(*wav)
            stats = delivery.voice_stats(*wav)
            segs = t.get("segments")
            secs = flat_sections(track, joins(segs), baseline, t["idx"], t.get("words"))
            for s in secs:
                s["turn_idx"] = t["idx"]
                s["session_start_ms"] = _round(wav_to_session(s["start_ms"], segs))
                s["session_end_ms"] = _round(wav_to_session(s["end_ms"], segs))
                s["provisional"] = THRESHOLDS_PROVISIONAL
                s["words"] = words_in(t.get("words"), s["start_ms"], s["end_ms"])
                s["advice_ok"] = s["advice_ok"] and bool(s["words"])  # advice quotes real words: none, no advice
            out[t["idx"]] = {"stats": stats, "flags": delivery.voice_flags(stats, baseline),
                             "usual": (baseline or {}).get("pitch_range_st"), "sections": secs}
            all_sections += secs
        except Exception as exc:  # audio trouble never fails a report
            log.warning("Voice evidence failed for turn %s: %s", t.get("idx"), exc)
    cap_session(all_sections)
    return out


def _round(v):
    return None if v is None else int(round(v))


def advised_sections(evidence: dict | None) -> list[dict]:
    """The sections that go to Claude for advice, in turn order."""
    return [s for idx in sorted(evidence or {}) for s in evidence[idx]["sections"] if s.get("advice_ok")]


def evidence_line(turn_idx: int, evidence: dict | None) -> str | None:
    """The indented line under a candidate turn in the report transcript, or None when it has no advised stretch."""
    ev = (evidence or {}).get(turn_idx)
    secs = [s for s in (ev or {}).get("sections", []) if s.get("advice_ok")]
    if not secs:
        return None
    parts = []
    pitch = (ev["stats"] or {}).get("pitch_range_st")
    if pitch is not None:
        parts.append(f"pitch range {pitch:.1f} st" + (f", your usual {ev['usual']:.1f}" if ev.get("usual") else ""))
    for s in secs:
        quote = " ".join(s["words"]).replace('"', "'")
        parts.append(f"flat stretch {s['id']} at {_fmt_time(s['start_ms'])}-{_fmt_time(s['end_ms'])} of this answer, "
                     f"range {s['range_st']:.1f} st over {round((s['end_ms'] - s['start_ms']) / 1000)} s, "
                     f'words: "{quote}"')
    return f"  (voice, measured: {'; '.join(parts)})"


def rules_text(evidence: dict | None) -> str:
    """The ``{voice_rules}`` slot of the report prompt: empty with no advised stretch (today's prompt)."""
    if not advised_sections(evidence):
        return ""
    return (Path(__file__).parent / "prompts" / "voice_rules.txt").read_text(encoding="utf-8")


def _tokens(text: str) -> list[str]:
    return [t for t in (re.sub(r"[^\w']", "", w.casefold()).strip("'") for w in str(text).split()) if t]


def clean_advice(items, sections_by_id: dict[str, dict]) -> list[dict]:
    """Keep the valid ``voice_advice`` items of one answer (``sections_by_id``: the sections of its turns).

    An item stays only when its section is one of the answer's, every stress word appears in that section's
    words (casefolded, punctuation stripped), and nothing in it names a feeling or trait (those are logged and
    dropped). ``say_it`` and ``why`` are cut at 300 characters. At most one item per section.
    """
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sec = sections_by_id.get(str(it.get("section") or "").strip())
        if sec is None or sec["id"] in seen:
            continue
        stress = [str(x).strip() for x in (it.get("stress") or []) if str(x).strip()][:3] if isinstance(it.get("stress"), list) else []
        say_it, why = str(it.get("say_it") or "").strip()[:_MAX_TEXT], str(it.get("why") or "").strip()[:_MAX_TEXT]
        spoken = {t for w in sec.get("words") or [] for t in _tokens(w)}
        if not stress or not say_it or not why or not all(t in spoken for x in stress for t in _tokens(x)):
            log.info("Dropped voice advice for %s: stress words are not in the stretch", sec["id"])
            continue
        if _STATE_RE.search(" ".join([*stress, say_it, why])):
            log.info("Dropped voice advice for %s: it names a feeling or trait", sec["id"])
            continue
        seen.add(sec["id"])
        out.append({"section": sec["id"], "stress": stress, "say_it": say_it, "why": why})
    return out


def answer_sections(mine: list[dict], evidence: dict | None, advice: list[dict] | None = None) -> list[dict]:
    """The sections of one answer's turns for ``delivery.voice.sections``, each with its ``advice`` when it has one."""
    by_id = {a["section"]: a for a in advice or []}
    out = []
    for t in mine:
        for s in (evidence or {}).get(t["idx"], {}).get("sections", []):
            s = dict(s)
            if s["id"] in by_id:
                s["advice"] = {k: by_id[s["id"]][k] for k in ("stress", "say_it", "why")}
            out.append(s)
    return out
