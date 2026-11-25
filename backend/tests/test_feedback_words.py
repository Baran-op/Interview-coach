"""V4: word timestamps for every spoken turn, filled before the report request (PLAN-voice.md)."""

import asyncio

from backend import db, feedback


def _t(idx, speaker="candidate", words=None, **kw):
    return {"idx": idx, "speaker": speaker, "text": "hello there", "words": words, "segments": None, "face": None,
            "t_start_ms": 0, "t_end_ms": 1000, **kw}


def test_turns_needing_words_cases(tmp_path):
    (tmp_path / "1.wav").write_bytes(b"x")
    (tmp_path / "5.wav").write_bytes(b"x")
    (tmp_path / "3.wav").write_bytes(b"x")
    turns = [_t(0, "interviewer"), _t(1), _t(2), _t(3, words=[]), _t(5, words=[{"w": "a", "start_ms": 0, "end_ms": 5}])]
    got = feedback.turns_needing_words(turns, tmp_path)
    assert [t["idx"] for t in got] == [1]  # 2 is typed (no WAV), 3 and 5 already have words (even an empty list)
    # no face and no segments is fine now; without an audio_dir every candidate turn lacking words counts
    assert [t["idx"] for t in feedback.turns_needing_words(turns)] == [1, 2]


def test_generate_fills_words_before_asking_claude(tmp_path, monkeypatch):
    from backend import gpu, stt

    sid = "s1"
    (tmp_path / sid).mkdir()
    (tmp_path / sid / "1.wav").write_bytes(b"x")
    turns = [_t(0, "interviewer"), _t(1)]
    seen, saved = {}, {}

    async def fake_ask(system, transcript, schema=None):
        seen["words"] = [t["words"] for t in turns if t["speaker"] == "candidate"]
        return {"summary": "s", "top_fixes": ["f"], "answers": [
            {"question_turn": 0, "question": "q", "answer_summary": "a", "scores": {}, "better_answer": "b", "tips": []}]}

    async def fake_run(fn, *args):
        return fn(*args)

    monkeypatch.setattr(db, "ANSWERS_DIR", tmp_path)
    monkeypatch.setattr(db, "get_session", lambda s: {"id": s, "pack_id": "p", "started_at": 0, "brief_json": None})
    monkeypatch.setattr(db, "get_pack", lambda p: {})
    monkeypatch.setattr(db, "list_turns", lambda s: turns)
    monkeypatch.setattr(db, "pack_report_history", lambda *a, **k: [])
    monkeypatch.setattr(db, "voice_baseline", lambda **k: None)
    monkeypatch.setattr(db, "face_baseline", lambda **k: None)
    monkeypatch.setattr(db, "set_turn_words", lambda s, i, w: saved.update({i: w}))
    monkeypatch.setattr(db, "save_report", lambda s, r, md: saved.update(report=r))
    monkeypatch.setattr(db, "set_overall_score", lambda *a: None)
    monkeypatch.setattr(db, "set_report_error", lambda s, m: saved.update(error=m))
    monkeypatch.setattr(gpu, "run", fake_run)
    monkeypatch.setattr(stt, "words_from_wav", lambda p: [{"w": "hello", "start_ms": 0, "end_ms": 300}])
    monkeypatch.setattr(feedback, "_ask_claude", fake_ask)
    asyncio.run(feedback.generate(sid))
    assert "error" not in saved, saved.get("error")
    assert seen["words"] == [[{"w": "hello", "start_ms": 0, "end_ms": 300}]]
    assert saved[1] == [{"w": "hello", "start_ms": 0, "end_ms": 300}]
