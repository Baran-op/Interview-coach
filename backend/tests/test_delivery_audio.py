"""Tests for delivery.audio_stats and per-answer assembly. Run from the repo root: pytest backend/tests"""

import math
import struct
import wave

from backend import delivery


def _wav(path, parts, rate=16000):
    """parts: [(seconds, amplitude)]; amplitude 0 = quiet noise floor."""
    samples = []
    for secs, amp in parts:
        for i in range(int(secs * rate)):
            tone = amp * math.sin(2 * math.pi * 200 * i / rate)
            samples.append(int(tone * 32767) + (i * 7919 % 21 - 10))  # tiny deterministic noise
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_audio_stats_finds_pauses(tmp_path):
    p = tmp_path / "a.wav"
    _wav(p, [(0.5, 0), (2, 0.3), (1.5, 0), (2, 0.3), (0.5, 0)])
    s = delivery.audio_stats(p)
    assert 3.8 <= s["speaking_s"] <= 4.3
    assert s["pauses_over_1s"] == 1
    assert 1.3 <= s["longest_pause_s"] <= 1.7


def test_audio_stats_span_gives_pause_time(tmp_path):
    p = tmp_path / "a.wav"
    _wav(p, [(0.3, 0), (3, 0.3), (0.3, 0)])
    s = delivery.audio_stats(p, span_s=10)
    assert s["pauses_over_1s"] == 0
    assert 6.5 <= s["pause_s"] <= 7.2


def test_audio_stats_short_dip_is_not_a_pause(tmp_path):
    p = tmp_path / "a.wav"
    _wav(p, [(0.3, 0), (1, 0.3), (0.15, 0), (1, 0.3), (0.3, 0)])
    assert delivery.audio_stats(p)["pauses_over_1s"] == 0


def test_audio_stats_bad_file(tmp_path):
    assert delivery.audio_stats(tmp_path / "missing.wav") is None
    (tmp_path / "bad.wav").write_bytes(b"nope")
    assert delivery.audio_stats(tmp_path / "bad.wav") is None


def _turn(idx, speaker, text, a=None, b=None):
    return {"idx": idx, "speaker": speaker, "text": text, "t_start_ms": a, "t_end_ms": b}


def test_answer_delivery_groups_follow_ups(tmp_path):
    turns = [
        _turn(0, "interviewer", "Tell me about yourself"),
        _turn(1, "candidate", "I led a team of five and we saved 20 percent, um, basically.", 0, 30000),
        _turn(2, "interviewer", "Which tools?"),
        _turn(3, "candidate", "Maybe Jira, I think.", 31000, 35000),
        _turn(4, "interviewer", "Why us?"),
        _turn(5, "candidate", "Your mission.", 40000, 42000),
    ]
    answers = [
        {"question_turn": 0, "category": "intro"},
        {"question_turn": 4, "category": "motivation"},
        {"question_turn": None, "category": "other"},
    ]
    _wav(tmp_path / "3.wav", [(0.2, 0), (1, 0.3), (1.5, 0), (1, 0.3), (0.2, 0)])
    delivery.answer_delivery(answers, turns, tmp_path)  # 1.wav and 5.wav are missing
    d = answers[0]["delivery"]
    assert d["seconds"] == 34.0 and d["first_answer_seconds"] == 30.0
    assert d["flag"] == "short" and d["target"] == [60, 90]
    assert d["hedges"] == 2 and d["fillers"] == 2 and d["numbers"] == 2
    assert d["pauses_over_1s"] == 1
    assert answers[1]["delivery"]["pauses_over_1s"] is None
    assert "delivery" not in answers[2]


def test_delivery_line():
    d = {"first_answer_seconds": 72, "target": [60, 90], "wpm": 138, "i_count": 6, "we_count": 2,
         "numbers": 3, "fillers": 2, "hedges": 1, "pauses_over_1s": None}
    assert delivery.delivery_line(d) == "1:12 (aim 1:00-1:30) · 138 wpm · I 6 / we 2 · 3 numbers · 2 fillers · 1 hedge"


# --- voice_stats ---------------------------------------------------------------------------

import numpy as np  # noqa: E402

_RATE = 16000


def _tone(secs, f0=150.0, f1=None, amp=0.3, fall=None):
    """Sine (or glide f0->f1) with a little harmonic content; ``fall`` = seconds over which the end fades to 10%."""
    n = int(secs * _RATE)
    f = np.linspace(f0, f1 if f1 else f0, n)
    ph = 2 * np.pi * np.cumsum(f) / _RATE
    y = amp * (np.sin(ph) + 0.4 * np.sin(2 * ph))
    if fall:
        k = int(fall * _RATE)
        y[-k:] *= np.linspace(1.0, 0.1, k)
    return y


def _speech(phrase, n=4, gap=0.5):
    quiet = np.zeros(int(gap * _RATE)) + 0.001 * np.sin(np.arange(int(gap * _RATE)))
    return np.concatenate([np.concatenate([phrase, quiet]) for _ in range(n)])


def test_voice_steady_tone_has_flat_pitch():
    v = delivery.voice_stats(_speech(_tone(2.5)), _RATE)
    assert v["pitch_range_st"] < 0.5
    assert v["voiced_s"] >= 8
    assert v["trail_off_pct"] == 0


def test_voice_glide_pitch_range():
    v = delivery.voice_stats(_speech(_tone(2.5, 110, 220)), _RATE)
    assert 8.5 <= v["pitch_range_st"] <= 10.5


def test_voice_trailing_off_phrases():
    v = delivery.voice_stats(_speech(_tone(2.5, fall=0.4)), _RATE)
    assert v["trail_off_pct"] == 100


def test_voice_too_little_speech_is_none():
    assert delivery.voice_stats(_tone(3), _RATE) is None


def test_voice_silence_and_noise_are_none():
    assert delivery.voice_stats(np.zeros(_RATE * 12), _RATE) is None
    noise = np.random.default_rng(0).normal(0, 0.1, _RATE * 12)
    assert delivery.voice_stats(noise, _RATE) is None
