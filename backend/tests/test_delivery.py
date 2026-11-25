"""Tests for delivery.text_stats. Run from the repo root: pytest backend/tests"""

import pytest

from backend import delivery, feedback
from backend.delivery import text_stats


def test_empty():
    assert text_stats("") == {"words": 0, "fillers": 0, "hedges": 0, "i_count": 0, "we_count": 0, "numbers": 0}


def test_words():
    assert text_stats("one  two\nthree\tfour")["words"] == 4


def test_fillers_reuse_feedback():
    t = "Um, I basically, you know, actually did it, like, a lot"
    assert text_stats(t)["fillers"] == feedback.filler_words([t])["count"] == 5


def test_like_not_filler_without_commas():
    assert text_stats("I'd like to use tools like Jira")["fillers"] == 0


@pytest.mark.parametrize(
    "text,n",
    [
        ("I think it worked", 1),
        ("I guess so, I suppose", 2),
        ("Maybe, perhaps, probably", 3),
        ("Hopefully it lands", 1),
        ("I feel like we did well", 1),
        ("i THINK so", 1),
        ("I thinking about it", 0),
        ("We shipped it", 0),
    ],
)
def test_hedges(text, n):
    assert text_stats(text)["hedges"] == n


def test_hedges_do_not_overlap_fillers():
    for h in ["I think", "I guess", "I suppose", "maybe", "perhaps", "probably", "hopefully", "I feel like"]:
        s = text_stats(h)
        assert s["hedges"] == 1 and s["fillers"] == 0, h
    for f in ["um", "uh", "you know", "I mean", "kind of", "sort of", "basically", "literally", "actually"]:
        assert text_stats(f)["hedges"] == 0, f


def test_i_count():
    s = text_stats("I led it. I'm proud, I've learned, I'd do it again. Ask me about my team.")
    assert s["i_count"] == 6 and s["we_count"] == 0


def test_i_count_curly_apostrophe_and_no_substrings():
    assert text_stats("I’m in")["i_count"] == 1
    assert text_stats("It is mine, my")["i_count"] == 1


def test_we_count():
    s = text_stats("We built it. We're live, we've grown, we'd scale. Give us our data.")
    assert s["we_count"] == 6 and s["i_count"] == 0


def test_we_not_substring():
    assert text_stats("answer weekly bus")["we_count"] == 0


def test_i_and_we_mixed():
    s = text_stats("We shipped and I owned the rollout for our team")
    assert (s["i_count"], s["we_count"]) == (1, 2)


@pytest.mark.parametrize(
    "text,n",
    [
        ("We had 12 people", 1),
        ("Grew 30% in 2 years", 2),
        ("Saved £5m and $2.5k", 2),
        ("Revenue of €1.2bn", 1),
        ("10,000 users", 1),
        ("Ten percent faster", 1),
        ("Two hundred thousand users", 1),
        ("Cut it in half and then double it", 2),
        ("a hundred calls, a million rows", 2),
        ("no figures here", 0),
        ("Went from 20 to 5 days", 2),
    ],
)
def test_numbers(text, n):
    assert text_stats(text)["numbers"] == n


def test_target_seconds():
    assert delivery.TARGET_SECONDS["intro"] == (60, 90)
    assert delivery.TARGET_SECONDS["motivation"] == (45, 90)
    assert delivery.TARGET_SECONDS["behavioural"] == (90, 150)
    assert "technical" not in delivery.TARGET_SECONDS


def test_voice_flags_without_baseline():
    v = lambda p, t=None: {"pitch_range_st": p, "trail_off_pct": t}  # noqa: E731
    assert delivery.voice_flags(v(3.0), None) == ["flat"]
    assert delivery.voice_flags(v(8.0), None) == []  # lively needs a baseline
    assert delivery.voice_flags(v(6.0, 40), None) == ["trailing"]
    assert delivery.voice_flags(v(6.0, 39), None) == []


def test_voice_flags_with_baseline():
    base = {"pitch_range_st": 5.0, "trail_off_pct": 20}
    v = lambda p, t=None: {"pitch_range_st": p, "trail_off_pct": t}  # noqa: E731
    assert delivery.voice_flags(v(3.7), base) == ["flat"]  # under 3.75
    assert delivery.voice_flags(v(3.8), base) == []
    assert delivery.voice_flags(v(6.3), base) == ["lively"]
    assert delivery.voice_flags(v(6.2), base) == []
    assert delivery.voice_flags(v(5, 40), base) == ["trailing"]
    assert delivery.voice_flags(v(5, 45), {"pitch_range_st": 5.0, "trail_off_pct": 35}) == []  # under 15 over usual
    assert delivery.voice_flags(v(3.0, 60), base) == ["flat", "trailing"]


def test_voice_flags_tolerate_missing():
    assert delivery.voice_flags(None, None) == []
    assert delivery.voice_flags({"pitch_range_st": None, "trail_off_pct": None}, {"pitch_range_st": None}) == []
    assert delivery.voice_fields(None, {"pitch_range_st": 5})["voice_usual"] is None


def test_delivery_line_voice_flags():
    d = {"first_answer_seconds": 70, "target": None, "wpm": None, "i_count": 1, "we_count": 0,
         "numbers": 1, "fillers": 0, "hedges": 0, "voice_flags": ["lively", "trailing"]}
    assert delivery.delivery_line(d).endswith("voice: lively, trailing off")
    d["voice_flags"] = []
    assert "voice" not in delivery.delivery_line(d)
    del d["voice_flags"]
    assert "voice" not in delivery.delivery_line(d)


def test_voice_baseline(tmp_path, monkeypatch):
    from backend import db

    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()
    pack = db.create_pack({"title": "t"})
    assert db.voice_baseline() is None
    for i in range(9):
        v = {"pitch_range_st": 4.0 + i, "loudness_range_db": 10.0, "trail_off_pct": None, "voiced_s": 20}
        db.add_attempt(f"a{i}", pack["id"], "k", "q", None, "x", 10, None, {"delivery": {"voice": v}})
    db.add_attempt("none", pack["id"], "k", "q", None, "x", 10, None, {"delivery": {"voice": None}})
    assert db.voice_baseline() is None  # 9 answers with voice stats
    db.add_attempt("a9", pack["id"], "k", "q", None, "x", 10, None, {"delivery": {"voice": {"pitch_range_st": 8.0}}})
    b = db.voice_baseline()
    assert b["pitch_range_st"] == 8.0 and b["loudness_range_db"] == 10.0 and b["trail_off_pct"] is None
    assert db.voice_baseline(exclude_attempt="a9") is None


def _face(frames=100, on=80.0, down=5.0, expr=4.0, found=100.0, spans=(), windows=(), t0=0, t1=60000):
    return {"t_start_ms": t0, "t_end_ms": t1, "frames": frames, "on_screen_pct": on, "looked_down_pct": down,
            "expressiveness": expr, "face_found_pct": found, "away_spans": list(spans), "expr_windows": list(windows)}


def test_combine_face_weights_by_frames():
    c = delivery.combine_face([_face(frames=100, on=100.0), _face(frames=300, on=60.0, t0=60000, t1=90000)])
    assert c["on_screen_pct"] == 70.0
    assert c["frames"] == 400 and c["t_start_ms"] == 0 and c["t_end_ms"] == 90000


def test_combine_face_tolerates_missing_and_null():
    assert delivery.combine_face([]) is None
    assert delivery.combine_face([None]) is None
    nulls = _face(frames=10, on=None, down=None, expr=None, found=20.0)
    c = delivery.combine_face([nulls])
    assert c["on_screen_pct"] is None and c["expressiveness"] is None
    c = delivery.combine_face([nulls, _face(frames=100, on=50.0)])  # the null turn is left out of the stat
    assert c["on_screen_pct"] == 50.0


def test_face_flags():
    assert delivery.face_flags(_face(down=30.0), None) == ["looking_down"]
    assert delivery.face_flags(_face(down=29.9), None) == []
    assert delivery.face_flags(_face(on=59.9), None) == ["low_eye_contact"]
    assert delivery.face_flags(_face(on=60.0), None) == []
    assert delivery.face_flags(_face(on=50.0, down=40.0), None) == ["looking_down", "low_eye_contact"]
    assert delivery.face_flags(_face(expr=0.1), None) == []  # no baseline, no still flag
    assert delivery.face_flags(_face(expr=3.4), {"expressiveness": 5.0}) == ["still"]  # under 3.5
    assert delivery.face_flags(_face(expr=3.5), {"expressiveness": 5.0}) == []
    assert delivery.face_flags(None, {"expressiveness": 5.0}) == []
    assert delivery.face_flags(_face(on=None, down=None, expr=None), {"expressiveness": 5.0}) == []


def test_face_moments_away_spans_and_still():
    spans = [{"start_ms": 42000, "end_ms": 51000, "kind": "down"}]
    wins = [{"start_ms": s, "value": 1.0} for s in range(0, 25000, 5000)] + [{"start_ms": 25000, "value": 4.0}]
    face = _face(spans=spans, windows=wins)
    ms = delivery.face_moments(face, {"expressiveness": 4.0})
    assert ms == [{"kind": "still", "start_ms": 0, "end_ms": 25000}, {"kind": "down", "start_ms": 42000, "end_ms": 51000}]
    # no baseline: only the away spans
    assert delivery.face_moments(face, None) == [{"kind": "down", "start_ms": 42000, "end_ms": 51000}]


def test_face_moments_still_needs_20s_of_consecutive_windows():
    base = {"expressiveness": 4.0}
    short = [{"start_ms": s, "value": 1.0} for s in (0, 5000, 10000)]  # 15 s
    assert delivery.face_moments(_face(windows=short), base) == []
    gap = [{"start_ms": s, "value": 1.0} for s in (0, 5000, 15000, 20000)]  # broken by a missing window
    assert delivery.face_moments(_face(windows=gap), base) == []
    edge = [{"start_ms": s, "value": 2.0} for s in (0, 5000, 10000, 15000)]  # 2.0 is not under half of 4.0
    assert delivery.face_moments(_face(windows=edge), base) == []
    four = [{"start_ms": s, "value": 1.9} for s in (0, 5000, 10000, 15000)]
    assert [m["kind"] for m in delivery.face_moments(_face(windows=four), base)] == ["still"]


def test_face_fields_and_line_without_face():
    assert delivery.face_fields(None, None) == {"face": None, "face_flags": [], "face_usual": None}
    d = {"first_answer_seconds": 70, "target": None, "wpm": 130, "i_count": 1, "we_count": 0,
         "numbers": 1, "fillers": 0, "hedges": 0}
    assert "eye contact" not in delivery.delivery_line(d)
    d.update(delivery.face_fields(_face(on=58.0, down=35.0, expr=2.0), {"expressiveness": 5.0}))
    assert delivery.delivery_line(d).endswith("eye contact 58% · mostly looking down · still face")
    assert d["face_usual"] == {"expressiveness": 5.0}


def test_face_moment_text_and_markdown():
    m = {"kind": "down", "start_ms": 42000, "end_ms": 51000}
    assert delivery.face_moment_text(m) == "Looked down 0:42–0:51 (9 s)"
    assert feedback._face_moments_md({"face": {"moments": [m]}}) == ["- Looked down 0:42–0:51 (9 s)", ""]
    assert feedback._face_moments_md(None) == [] and feedback._face_moments_md({"face": None}) == []
