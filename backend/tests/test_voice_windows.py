"""Pure parts of scripts/voice_windows.py (V3 calibration tool)."""

import csv
import wave

import numpy as np

from backend import delivery
from backend.tests.test_delivery_audio import _RATE, _speech, _tone
from scripts import voice_windows as vw


def test_group_from_text():
    assert vw.group_from_text("Normal one. So we started") == "normal"
    assert vw.group_from_text("  flat two, the project") == "flat"
    assert vw.group_from_text("Monotone three") == "flat"
    assert vw.group_from_text("varied four") == "varied"
    assert vw.group_from_text("So we started") is None and vw.group_from_text(None) is None


def test_percentiles():
    assert vw.percentiles([]) is None
    assert vw.percentiles([None, 2.0, 4.0, 6.0])["p50"] == 4.0


def _rows(spreads, path="a.wav"):
    return [{"path": path, "a": i * 100, "b": i * 100 + 333, "spread_st": s, "pitched": 100} for i, s in enumerate(spreads)]


def test_pick_clips_no_overlap_and_both_ends():
    rows = _rows([1, 1.1, 5, 9, 2, 8], "a.wav")  # a=0,100,200..: windows overlap (333 > 100)
    picked = vw.pick_clips(rows, n=2)
    by_path = [(r["a"], r["b"]) for r in picked]
    assert all(x[1] <= y[0] or x[0] >= y[1] for i, x in enumerate(by_path) for y in by_path[i + 1 :])
    assert picked[0]["spread_st"] == 1  # flattest first
    assert any(r["spread_st"] >= 8 for r in picked)


def test_agreement_and_flagged_share():
    rows = [{"spread_st": 1.0, "heard": True}, {"spread_st": 2.0, "heard": True},
            {"spread_st": 3.5, "heard": False}, {"spread_st": 2.2, "heard": False}, {"spread_st": 9, "heard": None}]
    a = vw.agreement(rows, 2.5)
    assert a == {"n": 4, "agree": 0.75, "flat_found": 1.0, "false_flags": 0.5}
    assert vw.agreement([], 2.5)["agree"] is None
    assert vw.flagged_share([1, 2, 3, 4], 2.5) == 0.5 and vw.flagged_share([], 2.5) is None


def test_thresholds_list():
    assert [t for _, t in vw.thresholds(None)] == [2.0, 2.5, 3.0]
    assert [round(t, 2) for _, t in vw.thresholds(4.0)][3:] == [2.0, 2.4, 2.8]


def test_measure_and_discover(tmp_path):
    x = _speech(_tone(2.5, 150), 6)
    (tmp_path / "drill").mkdir()
    for name in ("s.wav", "drill/abc.wav"):
        with wave.open(str(tmp_path / name), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(_RATE)
            w.writeframes((x * 32767).astype("<i2").tobytes())
    (tmp_path / "labels.csv").write_text("file,group\nabc.wav,Flat\n")
    g = vw.discover(tmp_path, tmp_path / "labels.csv")
    assert g[tmp_path / "s.wav"] == "interview" and g[tmp_path / "drill" / "abc.wav"] == "flat"
    m = vw.measure(tmp_path / "s.wav")
    assert m["windows"] and max(w["spread_st"] for w in m["windows"]) < 1
    assert vw.measure(tmp_path / "missing.wav") is None
    assert delivery._YIN_THRESHOLD == 0.15  # a --yin run restores the module value
    vw.measure(tmp_path / "s.wav", yin=0.2)
    assert delivery._YIN_THRESHOLD == 0.15
