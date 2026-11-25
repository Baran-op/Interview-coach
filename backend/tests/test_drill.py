"""Tests for the pure parts of drill mode. Run from the repo root: pytest backend/tests"""

import pytest

from backend import db, drill


def test_question_key_normalises():
    a = drill.question_key("Tell me about yourself.")
    assert len(a) == 12 and int(a, 16) >= 0
    assert a == drill.question_key("  tell   ME about, yourself?! ")
    assert a != drill.question_key("Tell me about your team")


def test_question_key_keeps_digits_and_words():
    assert drill.question_key("Why 2 years?") == drill.question_key("why 2 years")
    assert drill.question_key("Why 2 years?") != drill.question_key("why 3 years")


def test_build_result_clamps_and_averages():
    raw = {"scores": {"relevance": 9, "structure": "3", "specificity": 0, "evidence": None},
           "tips": ["a", "", "b"], "improved": None, "better_answer": None}
    r = drill.build_result(raw, "I did it, um, in 2 weeks", 12.0)
    assert r["scores"] == {"relevance": 5, "structure": 3, "specificity": 1, "evidence": 1}
    assert r["average"] == 2.5
    assert r["tips"] == ["a", "b"] and r["improved"] == [] and r["better_answer"] == ""
    assert r["delivery"]["words"] == 7 and r["delivery"]["fillers"] == 1 and r["delivery"]["seconds"] == 12.0


def test_build_result_empty_raw():
    r = drill.build_result({}, "", None)
    assert r["average"] == 1.0 and r["delivery"]["seconds"] is None


PACK = {"id": "p1", "company": "Acme"}


def _report(*answers):
    return {"answers": [{"question": q, "average": avg, "category": "behavioural"} for q, avg in answers]}


def test_starters_use_company():
    qs = drill.assemble_questions(PACK, [], [])
    assert [q["source"] for q in qs] == ["starter"] * 5
    assert "Why Acme?" in [q["question"] for q in qs]
    assert drill.assemble_questions({"id": "p"}, [], [])[2]["question"] == "Why this company?"


def test_weak_report_questions_newest_first_deduped():
    reports = [  # newest first
        _report(("Describe a conflict.", 2.0), ("Tell me about a win.", 4.0)),
        _report(("Describe a conflict", 1.5), ("Handle pressure?", 2.5), ("Easy one?", 2.6)),
    ]
    qs = drill.assemble_questions(PACK, reports, [])
    weak = [q["question"] for q in qs if q["source"] == "report"]
    assert weak == ["Describe a conflict.", "Handle pressure?"]


def test_weak_question_matching_starter_not_duplicated():
    qs = drill.assemble_questions(PACK, [_report(("Tell me about yourself", 2.0))], [])
    assert len(qs) == 5 and qs[0]["source"] == "starter"


def _attempt(question, avg, aid):
    return {"id": aid, "question_key": drill.question_key(question), "question": question,
            "category": "other", "result": {"average": avg}}


def test_attempt_summaries_and_custom_questions():
    attempts = [
        _attempt("Tell me about yourself.", 2.0, "a"),
        _attempt("Tell me about yourself.", 3.5, "b"),
        _attempt("Tell me about yourself.", 3.0, "c"),
        _attempt("My own question?", 4.0, "d"),
    ]
    qs = drill.assemble_questions(PACK, [], attempts)
    first = qs[0]
    assert (first["attempts"], first["latest"], first["best"]) == (3, 3.0, 3.5)
    assert qs[1]["attempts"] == 0 and qs[1]["latest"] is None and qs[1]["best"] is None
    custom = qs[-1]
    assert custom["source"] == "custom" and custom["question"] == "My own question?" and custom["best"] == 4.0
    assert len(qs) == 6


def test_prompts_in_step():
    """Both prompts get their criteria from the one shared renderer, for the default and for a brief."""
    from backend import brief, feedback
    from backend.tests.test_brief import _raw

    for name in ("drill.txt", "feedback.txt"):
        text = (drill.PROMPTS_DIR / name).read_text()
        assert "{criteria_block}" in text and "{json_scores}" in text and "{n_criteria}" in text
    for b in (None, brief.clean_brief(_raw())):
        block = brief.render_criteria((b or brief.default_brief())["criteria"])
        assert block in drill.system_prompt({"role": "R"}, b)
        assert block in feedback._system_prompt({"role": "R"}, None, b)
    assert "{role}" not in drill.system_prompt({"role": "R"})


def test_user_prompt_with_previous():
    prev = {"answer_text": "old answer", "seconds": 30, "result": {"average": 2.0, "scores": {"relevance": 2}}}
    p = drill.user_prompt("Q?", "intro", "new answer", 40.2, prev)
    assert "Answer (40 s, 2 words)" in p and "old answer" in p and "average 2.0" in p
    assert "Previous attempt" not in drill.user_prompt("Q?", "intro", "new", None, None)


def test_delete_pack_removes_attempts_and_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "ANSWERS_DIR", tmp_path / "answers")
    db.init()
    pack = db.create_pack({"title": "T"})
    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF")
    db.add_attempt("a1", pack["id"], "k", "Q?", "intro", "ans", 5.0, str(audio), {"average": 3.0})
    got = db.list_attempts(pack["id"], "k")
    assert got[0]["result"]["average"] == 3.0
    paths = db.delete_pack(pack["id"])
    assert paths == [str(audio)]
    assert db.list_attempts(pack["id"]) == []
