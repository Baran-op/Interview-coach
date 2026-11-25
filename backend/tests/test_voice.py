"""Tests for backend/voice.py (PLAN-voice.md). Run from the repo root: pytest backend/tests"""

import numpy as np

from backend import delivery, voice

SEGS = [{"start_ms": 1000, "end_ms": 5000}, {"start_ms": 9000, "end_ms": 12000}, {"start_ms": 12000, "end_ms": 13000}]


def test_no_segments_returns_none():
    for s in (None, [], [{"start_ms": 5, "end_ms": 5}]):
        assert voice.wav_to_session(100, s) is None
        assert voice.session_to_wav(100, s) is None
        assert voice.joins(s) == []


def test_wav_to_session_walks_segments():
    assert voice.wav_to_session(0, SEGS) == 1000
    assert voice.wav_to_session(2000, SEGS) == 3000
    assert voice.wav_to_session(4500, SEGS) == 9500
    assert voice.wav_to_session(7500, SEGS) == 12500
    assert voice.wav_to_session(99999, SEGS) == 13000  # past the end snaps to the last edge
    assert voice.wav_to_session(-5, SEGS) == 1000


def test_session_to_wav_and_round_trip():
    assert voice.session_to_wav(3000, SEGS) == 2000
    assert voice.session_to_wav(9500, SEGS) == 4500
    for w in (0, 1, 1999, 4000, 4001, 6999, 8000):
        assert voice.session_to_wav(voice.wav_to_session(w, SEGS), SEGS) in (w, 4000)  # a join edge is the same instant twice


def test_times_in_a_gap_snap_to_the_nearest_edge():
    assert voice.session_to_wav(6000, SEGS) == 4000  # closer to the end of segment 1
    assert voice.session_to_wav(8500, SEGS) == 4000  # closer to the start of segment 2 (same WAV instant)
    assert voice.session_to_wav(0, SEGS) == 0
    assert voice.session_to_wav(50000, SEGS) == 8000


def test_joins_only_where_silence_was_cut():
    assert voice.joins(SEGS) == [{"wav_ms": 4000, "cut_ms": 4000}]  # the 12000 -> 12000 boundary is no cut
    assert voice.joins(SEGS[:1]) == []


def test_pitch_track_shape_and_values():
    from backend.tests.test_delivery_audio import _RATE, _speech, _tone

    tr = delivery.pitch_track(_speech(_tone(2.5, 150), 2), _RATE)
    assert tr["frame_ms"] == 30
    assert len(tr["f0_hz"]) == len(tr["voiced"]) == len(tr["rms_db"]) == 200
    pitched = tr["f0_hz"][~np.isnan(tr["f0_hz"])]
    assert len(pitched) > 100 and abs(float(np.median(pitched)) - 150) < 2
    assert not tr["voiced"][~np.isnan(tr["f0_hz"])].tolist().count(False)  # only voiced frames get a pitch
    assert delivery.pitch_track(np.zeros(10), _RATE) is None


def test_to_semitones_folds_and_cuts():
    st = delivery.to_semitones([100.0, 200.0, 50.0, 150.0, np.nan, 100 * 2 ** (20 / 12)], 100.0)
    assert st[0] == 0
    assert np.isclose(st[1], 0) and np.isclose(st[2], 0)  # an octave up or down folds back
    assert np.isclose(st[3], 12 * np.log2(1.5)) and st[3] < 9
    assert np.isnan(st[4])
    assert np.isclose(st[5], 8)  # +20 st folds to +8
