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
