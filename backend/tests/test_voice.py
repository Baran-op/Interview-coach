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


# --- V2: flat sections -------------------------------------------------------------------------

from backend import voice as V  # noqa: E402


def _track(f0, voiced=None):
    f0 = np.asarray(f0, dtype=float)
    return {"frame_ms": 30, "f0_hz": f0, "voiced": ~np.isnan(f0) if voiced is None else voiced, "rms_db": np.zeros(len(f0))}


def _steady(secs, hz=150.0, pitched=1.0, seed=0):
    n = int(secs / 0.03)
    f0 = np.full(n, hz) * (1 + np.random.default_rng(seed).normal(0, 0.002, n))
    if pitched < 1:
        f0[np.random.default_rng(seed + 1).random(n) > pitched] = np.nan
    return f0


def _voiced_all(f0):
    return np.ones(len(f0), dtype=bool)


def test_steady_20_s_is_one_section():
    f0 = _steady(20)
    s = V.flat_sections(_track(f0, _voiced_all(f0)), [], None, turn_idx=5)
    assert len(s) == 1 and s[0]["id"] == "T5.1"
    assert s[0]["start_ms"] <= 100 and s[0]["end_ms"] >= 19800
    assert s[0]["range_st"] < 0.5 and s[0]["advice_ok"] is True


def test_glide_has_no_section():
    n = int(20 / 0.03)
    f0 = 150 * 2 ** (np.linspace(0, 8, n) / 12)  # 8 st glide: every 10 s window spans about 3 st
    assert V.flat_sections(_track(f0, _voiced_all(f0)), [], None) == []


def test_long_cut_join_splits_into_two_sections():
    f0 = _steady(24)
    joined = [{"wav_ms": 12000, "cut_ms": 3000}]
    s = V.flat_sections(_track(f0, _voiced_all(f0)), joined, None)
    assert len(s) == 2
    assert s[0]["end_ms"] <= 12000 + 30 and s[1]["start_ms"] >= 12000 - 30
    # a short cut (under 2 s) is not a reset
    assert len(V.flat_sections(_track(f0, _voiced_all(f0)), [{"wav_ms": 12000, "cut_ms": 1000}], None)) == 1


def test_thirty_percent_pitched_still_counts_and_ten_percent_does_not():
    f0 = _steady(20, pitched=0.3)
    assert len(V.flat_sections(_track(f0, _voiced_all(f0)), [], None)) == 1
    f0 = _steady(20, pitched=0.1)  # about 33 pitched frames per window, under 60
    assert V.flat_sections(_track(f0, _voiced_all(f0)), [], None) == []


def test_short_turns_get_no_sections():
    f0 = _steady(11.5)
    assert V.flat_sections(_track(f0, _voiced_all(f0)), [], None) == []
    f0 = _steady(14)
    voiced = np.zeros(len(f0), dtype=bool)
    voiced[: int(7 / 0.03)] = True  # only 7 s voiced
    assert V.flat_sections(_track(f0, voiced), [], None) == []


def test_baseline_threshold_versus_fallback():
    rng = np.random.default_rng(3)
    n = int(20 / 0.03)
    f0 = 150 * 2 ** (rng.uniform(-1.5, 1.5, n) / 12)  # window spread about 2.4 st
    t = _track(f0, _voiced_all(f0))
    assert V.flat_sections(t, [], None)  # under 2.5 st with no baseline
    assert V.flat_sections(t, [], {"window_range_st": 3.0}) == []  # 0.6 x 3.0 = 1.8 st
    assert V.flat_sections(t, [], {"window_range_st": 6.0})  # 3.6 st
    assert V.flat_threshold({"window_range_st": 5.0}) == 3.0 and V.flat_threshold({}) == 2.5


def test_caps_and_order():
    # three flat stretches of different flatness separated by wide-ranging speech
    rng = np.random.default_rng(1)

    def lively(secs):
        n = int(secs / 0.03)
        return 150 * 2 ** (rng.uniform(-6, 6, n) / 12)

    def flat(secs, jitter):
        n = int(secs / 0.03)
        return 150 * 2 ** (rng.uniform(-jitter, jitter, n) / 12)

    f0 = np.concatenate([flat(12, 0.5), lively(12), flat(12, 0.2), lively(12), flat(12, 1.0)])
    s = V.flat_sections(_track(f0, _voiced_all(f0)), [], None, turn_idx=2)
    assert [x["id"] for x in s] == ["T2.1", "T2.2", "T2.3"]
    assert [x["start_ms"] for x in s] == sorted(x["start_ms"] for x in s)
    assert [x["advice_ok"] for x in s] == [True, True, False] or sum(x["advice_ok"] for x in s) == 2
    assert not [x for x in s if x["range_st"] > 2.5]
    assert min(s, key=lambda x: x["range_st"])["advice_ok"]
    assert not max(s, key=lambda x: x["range_st"])["advice_ok"]


def test_cap_session_keeps_flattest_six():
    secs = [{"id": f"T{i}.1", "range_st": float(i), "advice_ok": True} for i in range(1, 9)]
    V.cap_session(secs)
    assert [s["id"] for s in secs if s["advice_ok"]] == [f"T{i}.1" for i in range(1, 7)]


def test_edges_snap_to_words():
    f0 = _steady(20)
    words = [{"w": "a", "start_ms": 300, "end_ms": 900}, {"w": "b", "start_ms": 1000, "end_ms": 1500},
             {"w": "z", "start_ms": 19000, "end_ms": 19400}]
    s = V.flat_sections(_track(f0, _voiced_all(f0)), [], None, words=words)
    assert s[0]["start_ms"] == 300 and s[0]["end_ms"] == 19400
