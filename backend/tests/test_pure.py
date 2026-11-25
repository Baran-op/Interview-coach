"""Unit tests for pure functions. Run from the repo root: pytest backend/tests"""

import pytest

from backend import brain, feedback, stt


def test_parse_tags_strips_and_indexes():
    r = brain.parse_tags("[smile] Hello there. [thinking] Tell me more.")
    assert r.text == "Hello there. Tell me more."
    assert r.expressions == [
        {"tag": "smile", "char_index": 0},
        {"tag": "thinking", "char_index": len("Hello there. ")},
    ]
    assert not r.is_final


def test_parse_tags_end():
    r = brain.parse_tags("Thanks, goodbye. [END]")
    assert r.is_final and r.text == "Thanks, goodbye." and r.expressions == []


def test_parse_tags_plain():
    r = brain.parse_tags("No tags here")
    assert r.text == "No tags here" and r.expressions == [] and not r.is_final


def test_filler_words_counts():
    out = feedback.filler_words(["Um, so basically I, like, did it. Ummm you know."])
    assert out["count"] == 5
    assert out["by_word"]["um"] == 2
    assert out["by_word"]["basically"] == 1 and out["by_word"]["like"] == 1


def test_filler_words_ignores_plain_like():
    assert feedback.filler_words(["I'd like to use tools like Jira."])["count"] == 0


def _raw(scores):
    return {"summary": "s", "top_fixes": ["a", "b", "c", "d"],
            "answers": [{"question_turn": 1, "question": "q", "scores": scores, "tips": ["t"]}]}


def test_normalise_clamps_and_averages():
    turns = [{"speaker": "candidate", "text": "um hello"}]
    rep = feedback.normalise(
        _raw({"relevance": 9, "structure": "x", "specificity": 3, "evidence": 4}), turns)
    a = rep["answers"][0]
    assert a["scores"] == {"relevance": 5, "structure": 1, "specificity": 3, "evidence": 4}
    assert a["average"] == 3.2 and rep["overall_score"] == 3.2
    assert len(rep["top_fixes"]) == 3
    assert rep["filler_words"]["count"] == 1


def test_normalise_requires_answers():
    with pytest.raises(feedback.FeedbackError):
        feedback.normalise({"answers": []}, [])


def test_keyword_prompt():
    p = stt.keyword_prompt("Consultant", "Acme", ["We use Dynamics 365 and Power BI with SQL."])
    assert "Acme" in p and "Dynamics 365" in p and "SQL" in p
    assert len(p) <= 900


def test_keyword_prompt_empty():
    assert "a role" in stt.keyword_prompt("", "", [])


def test_is_partial():
    from backend import db

    assert db.MIN_SCORED_ANSWERS == 3
    assert db.is_partial(0) and db.is_partial(2)
    assert not db.is_partial(3) and not db.is_partial(10)
    assert not db.is_partial(None)


def test_session_summary_partial_flag():
    import json
    import sqlite3

    from backend import db

    def row(n):
        report = None
        if n is not None:
            a = {"scores": {c: 3 for c in db.CRITERIA}}
            report = json.dumps({"answers": [a] * n})
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT 'x' AS id, ? AS report_json", (report,)).fetchone()

    assert db._session_summary(row(2))["partial"] is True
    assert db._session_summary(row(3))["partial"] is False
    assert db._session_summary(row(None))["partial"] is False
