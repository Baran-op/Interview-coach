"""V7: answer audio and voice track routes (PLAN-voice.md). Temp DATA_DIR, synthetic WAVs, no models."""

import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import db, main, voice
from backend.tests.test_delivery_audio import _RATE, _speech, _tone


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "ANSWERS_DIR", tmp_path / "answers")
    db.init()
    voice._CACHE.clear()
    return TestClient(main.app)


def _write_wav(path, x):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(_RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def _session(client):
    """A session with an interviewer turn 0, a typed answer 1, a spoken answer 2 (24 s steady tone, one segment)
    and a spoken answer 3 whose WAV was lost. Returns the session id."""
    pack = db.create_pack({"title": "t"})
    sid = db.create_session(pack["id"])
    for speaker in ("interviewer", "candidate", "candidate", "candidate"):
        db.add_turn(sid, speaker, "some text")
    db.set_turn_segments(sid, 2, [{"start_ms": 1000, "end_ms": 25000}])
    db.set_turn_segments(sid, 3, [{"start_ms": 30000, "end_ms": 33000}])
    db.set_turn_words(sid, 2, [{"w": f"w{i}", "start_ms": i * 400, "end_ms": i * 400 + 300} for i in range(60)])
    _write_wav(db.ANSWERS_DIR / sid / "2.wav", _speech(_tone(2.5, 150), 8))
    return sid


def test_unknown_session_or_turn_is_404(client):
    assert client.get("/sessions/nope/turns/0/audio").status_code == 404
    assert client.get("/sessions/nope/turns/0/voice").status_code == 404
    sid = _session(client)
    assert client.get(f"/sessions/{sid}/turns/99/audio").status_code == 404
    assert client.get(f"/sessions/{sid}/turns/99/voice").status_code == 404
    assert client.get(f"/sessions/{sid}/turns/abc/audio").status_code == 422  # idx is an int
    assert client.get(f"/sessions/{sid}/turns/0/voice").status_code == 404  # an interviewer turn is not an answer


def test_audio_serves_the_wav_with_ranges(client):
    sid = _session(client)
    full = client.get(f"/sessions/{sid}/turns/2/audio")
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav"
    assert full.content[:4] == b"RIFF" and full.headers["accept-ranges"] == "bytes"
    part = client.get(f"/sessions/{sid}/turns/2/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(full.content)}"
    assert client.get(f"/sessions/{sid}/turns/1/audio").status_code == 404  # typed: no file
    assert client.get(f"/sessions/{sid}/turns/3/audio").status_code == 404  # file lost


def test_voice_reasons_for_typed_and_missing_audio(client):
    sid = _session(client)
    typed = client.get(f"/sessions/{sid}/turns/1/voice").json()
    assert typed["reason"] == "typed" and typed["pitch_st"] == [] and typed["sections"] == []
    lost = client.get(f"/sessions/{sid}/turns/3/voice").json()
    assert lost["reason"] == "no_audio" and lost["segments"] == [{"start_ms": 30000, "end_ms": 33000}]


def test_voice_payload_for_a_spoken_turn(client):
    sid = _session(client)
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert set(v) == {"duration_ms", "frame_ms", "pitch_st", "center_hz", "usual", "segments", "joins", "words", "words_pending",
                      "sections", "sections_stored", "stats", "reason"}
    assert v["reason"] is None and v["frame_ms"] == 30 and abs(v["duration_ms"] - 24000) < 5
    assert len(v["pitch_st"]) == 800 and any(x is None for x in v["pitch_st"])
    assert all(x is None or abs(x) < 0.5 for x in v["pitch_st"])  # a steady tone, relative to its own median
    assert abs(v["center_hz"] - 150) < 2 and v["usual"] is None  # no baseline yet
    assert v["segments"] == [{"start_ms": 1000, "end_ms": 25000}] and v["joins"] == []
    assert len(v["words"]) == 60 and v["words_pending"] is False
    assert v["stats"]["pitch_range_st"] == 0.0
    assert v["sections_stored"] is False and [s["id"] for s in v["sections"]] == ["T2.1"]
    assert v["sections"][0]["words"] and v["sections"][0]["session_start_ms"] >= 1000


def test_words_pending_while_an_interview_is_live(client, monkeypatch):
    sid = _session(client)
    db.set_turn_words(sid, 2, None)
    monkeypatch.setitem(main.LIVE, "other", object())
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert v["words"] is None and v["words_pending"] is True and v["sections"][0]["id"] == "T2.1"


def test_words_filled_and_saved_for_an_older_session(client, monkeypatch):
    from backend import gpu, stt

    sid = _session(client)
    db.set_turn_words(sid, 2, None)
    calls = []

    async def fake_run(fn, *a):
        calls.append(a)
        return [{"w": "hello", "start_ms": 0, "end_ms": 200}]

    monkeypatch.setattr(gpu, "run", fake_run)
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert v["words"] == [{"w": "hello", "start_ms": 0, "end_ms": 200}] and len(calls) == 1
    assert db.list_turns(sid)[2]["words"] == v["words"]
    client.get(f"/sessions/{sid}/turns/2/voice")
    assert len(calls) == 1  # saved, not recomputed


def test_stored_sections_win_when_the_report_has_them(client):
    sid = _session(client)
    stored = {"id": "T2.1", "turn_idx": 2, "start_ms": 100, "end_ms": 20000, "range_st": 0.1, "advice": {"stress": ["w1"], "say_it": "x", "why": "y"}}
    report = {"overall_score": 3, "summary": "", "top_fixes": [], "filler_words": {}, "answers": [
        {"question_turn": 0, "question": "q", "category": "other", "delivery": {"voice": {"sections": [stored]}}}]}
    db.set_report_pending(sid)
    db.save_report(sid, report, "md")
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert v["sections_stored"] is True and v["sections"] == [stored]


def test_usual_band_and_centre_come_from_the_baseline(client):
    sid = _session(client)
    pack = db.create_pack({"title": "p2"})
    for i in range(10):
        db.add_attempt(f"a{i}", pack["id"], "k", "q", None, "x", 10, None, {"delivery": {"voice": {
            "pitch_range_st": 5.0, "center_hz": 120.0, "p10_st": -2.0, "p90_st": 3.0}}})
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert v["center_hz"] == 120.0 and v["usual"] == {"p10_st": -2.0, "p90_st": 3.0}
    assert abs(np.nanmean([x for x in v["pitch_st"] if x is not None]) - 12 * np.log2(150 / 120)) < 0.3  # relative to the usual centre


def test_too_short_still_gives_the_graph(client):
    sid = _session(client)
    _write_wav(db.ANSWERS_DIR / sid / "2.wav", _speech(_tone(2.5, 150), 2))
    v = client.get(f"/sessions/{sid}/turns/2/voice").json()
    assert v["reason"] == "too_short" and v["sections"] == [] and v["stats"] is None and len(v["pitch_st"]) > 0


# --- V11 backend: a drill attempt stores its flat stretches, words gathered alongside the scoring ---

def _drill_client(client, monkeypatch, order):
    import asyncio

    from backend import drill, gpu, stt

    async def fake_score(pack, question, category, answer, seconds, previous, current):
        order.append("score-start")
        await asyncio.sleep(0.05)
        order.append("score-end")
        return {"average": 3.0, "scores": {}, "tips": [], "improved": [], "better_answer": "b", "delivery": {"seconds": 24}}

    async def fake_run(fn, *a):
        if fn is stt.words_from_wav:
            order.append("words")
            return [{"w": f"w{i}", "start_ms": i * 400, "end_ms": i * 400 + 300} for i in range(60)]
        return "hello there"

    monkeypatch.setattr(drill, "score", fake_score)
    monkeypatch.setattr(gpu, "run", fake_run)
    monkeypatch.setattr(stt, "is_ready", lambda: True)
    monkeypatch.setattr(db, "DRILL_DIR", db.ANSWERS_DIR / "drill")
    return db.create_pack({"title": "t", "materials": [{"name": "jd", "kind": "job", "source": "paste", "text": "x"}]})


def _wav_bytes(tmp_path, x):
    p = tmp_path / "up.wav"
    _write_wav(p, x)
    return p.read_bytes()


def test_drill_attempt_stores_sections_and_runs_words_beside_scoring(client, monkeypatch, tmp_path):
    order = []
    pack = _drill_client(client, monkeypatch, order)
    audio = _wav_bytes(tmp_path, _speech(_tone(2.5, 150), 8))
    r = client.post(f"/packs/{pack['id']}/drill/attempts", data={"question": "Tell me about a go-live", "category": "other",
                    "seconds": "24", "segments": '[{"start_ms": 0, "end_ms": 24000}]'}, files={"audio": ("a.wav", audio, "audio/wav")})
    assert r.status_code == 200, r.text
    assert order.index("words") < order.index("score-end")  # gathered, not run after the scoring request
    v = r.json()["attempt"]["result"]["delivery"]["voice"]
    assert v["pitch_range_st"] == 0.0 and len(v["sections"]) == 1
    s = v["sections"][0]
    assert s["id"] == "T0.1" and s["words"] and s["advice_ok"] is False and s["session_start_ms"] is not None
    stored = db.list_attempts(pack["id"])[0]["result"]["delivery"]["voice"]["sections"]
    assert stored == v["sections"]


def test_drill_attempt_too_short_has_no_sections_and_a_failed_score_keeps_no_file(client, monkeypatch, tmp_path):
    from backend import drill

    order = []
    pack = _drill_client(client, monkeypatch, order)
    short = _wav_bytes(tmp_path, _speech(_tone(2.5, 150), 2))
    r = client.post(f"/packs/{pack['id']}/drill/attempts", data={"question": "q", "category": "other"},
                    files={"audio": ("a.wav", short, "audio/wav")})
    assert r.status_code == 200 and r.json()["attempt"]["result"]["delivery"]["voice"] is None

    async def failing(*a):
        raise drill.DrillError("no")

    monkeypatch.setattr(drill, "score", failing)
    before = set((db.ANSWERS_DIR / "drill").glob("*.wav"))
    r = client.post(f"/packs/{pack['id']}/drill/attempts", data={"question": "q2", "category": "other"},
                    files={"audio": ("a.wav", short, "audio/wav")})
    assert r.status_code == 502 and set((db.ANSWERS_DIR / "drill").glob("*.wav")) == before
