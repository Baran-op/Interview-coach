"""Tests for face.clean_face (validation of the browser's per-answer face stats)."""

import json

from backend.face import MAX_SPANS, clean_face

BASE = {"t_start_ms": 10_000, "t_end_ms": 40_000, "on_screen_pct": 80, "looked_down_pct": 5,
        "face_found_pct": 99, "expressiveness": 3.2, "frames": 240}


def test_valid_roundtrip_from_string():
    raw = {**BASE, "away_spans": [{"start_ms": 12_000, "end_ms": 16_000, "kind": "down"}],
           "expr_windows": [{"start_ms": 10_000, "value": 2.5}]}
    out = clean_face(json.dumps(raw), 60_000)
    assert out["on_screen_pct"] == 80 and out["frames"] == 240
    assert out["away_spans"] == [{"start_ms": 12_000, "end_ms": 16_000, "kind": "down"}]
    assert out["expr_windows"] == [{"start_ms": 10_000, "value": 2.5}]


def test_unknown_keys_dropped():
    out = clean_face({**BASE, "emotion": "nervous", "frame": "AAAA"}, 60_000)
    assert "emotion" not in out and "frame" not in out


def test_numbers_clamped_and_nulls_kept():
    out = clean_face({**BASE, "on_screen_pct": 250, "looked_down_pct": -3, "expressiveness": None,
                      "frames": 10**9}, 60_000)
    assert out["on_screen_pct"] == 100 and out["looked_down_pct"] == 0
    assert out["expressiveness"] is None and out["frames"] == 20_000


def test_non_numbers_become_none():
    out = clean_face({**BASE, "on_screen_pct": "80", "face_found_pct": True, "expressiveness": float("nan")}, 60_000)
    assert out["on_screen_pct"] is None and out["face_found_pct"] is None and out["expressiveness"] is None


def test_spans_clipped_to_turn_range():
    spans = [{"start_ms": 5_000, "end_ms": 20_000, "kind": "away"},   # starts before: clipped to 10 s
             {"start_ms": 30_000, "end_ms": 90_000, "kind": "down"},  # ends after: clipped to 40 s
             {"start_ms": 50_000, "end_ms": 60_000, "kind": "down"},  # fully outside: empty, dropped
             {"start_ms": 20_000, "end_ms": 25_000, "kind": "sad"},   # unknown kind
             {"start_ms": 25_000, "end_ms": 25_000, "kind": "down"}]  # empty
    out = clean_face({**BASE, "away_spans": spans}, 60_000)
    assert out["away_spans"] == [{"start_ms": 10_000, "end_ms": 20_000, "kind": "away"},
                                 {"start_ms": 30_000, "end_ms": 40_000, "kind": "down"}]


def test_times_cannot_exceed_session_elapsed():
    out = clean_face({**BASE, "t_end_ms": 10**9}, 45_000)
    assert out["t_end_ms"] == 45_000


def test_lists_capped():
    spans = [{"start_ms": 10_000 + i * 100, "end_ms": 10_050 + i * 100, "kind": "down"} for i in range(100)]
    wins = [{"start_ms": 10_000, "value": 1} for _ in range(1000)]
    out = clean_face({**BASE, "away_spans": spans, "expr_windows": wins}, 60_000)
    assert len(out["away_spans"]) == MAX_SPANS and len(out["expr_windows"]) == 120


def test_garbage_returns_none():
    assert clean_face(None, 60_000) is None
    assert clean_face("not json", 60_000) is None
    assert clean_face("[1, 2]", 60_000) is None
    assert clean_face({"on_screen_pct": 50}, 60_000) is None  # no time range
    assert clean_face({**BASE, "t_end_ms": 5_000}, 60_000) is None  # end before start
    assert clean_face("x" * 100_000, 60_000) is None
