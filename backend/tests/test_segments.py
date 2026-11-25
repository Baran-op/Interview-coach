"""Tests for segments.clean_segments (validation of the browser's per-answer speech segments)."""

import json

from backend.segments import MAX_SEGMENTS, clean_segments


def test_valid_from_string_and_list():
    raw = [{"start_ms": 1000, "end_ms": 4000}, {"start_ms": 9000, "end_ms": 12000}]
    assert clean_segments(json.dumps(raw), 60_000) == raw
    assert clean_segments(raw, 60_000) == raw


def test_garbage_is_none():
    for raw in (None, "", "not json", "{}", 5, [], [{"start_ms": "a", "end_ms": 5}], [{"start_ms": 5}]):
        assert clean_segments(raw, 60_000) is None


def test_bad_segments_dropped():
    raw = [
        {"start_ms": 1000, "end_ms": 4000},
        {"start_ms": 3000, "end_ms": 5000},       # overlaps the previous one
        {"start_ms": 8000, "end_ms": 7000},       # backwards
        {"start_ms": 9000, "end_ms": 99_000},     # in the future
        {"start_ms": True, "end_ms": 20_000},     # boolean
        {"start_ms": float("nan"), "end_ms": 20_000},
        "x",
        {"start_ms": 10_000, "end_ms": 12_000},
    ]
    assert clean_segments(raw, 60_000) == [{"start_ms": 1000, "end_ms": 4000}, {"start_ms": 10_000, "end_ms": 12_000}]


def test_capped():
    raw = [{"start_ms": i * 10, "end_ms": i * 10 + 5} for i in range(MAX_SEGMENTS + 50)]
    assert len(clean_segments(raw, 10_000_000)) == MAX_SEGMENTS
