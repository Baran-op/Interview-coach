"""Rubric from the brief (PLAN-brief I4): reports and attempts carry the rubric they were scored with."""

import json

import pytest

from backend import brief, db, delivery, drill, feedback
from backend.categories import resolve_category
from backend.tests.test_brief import _raw

BRIEF = brief.clean_brief(_raw())  # stations: clinical_scenario / clinical_scenario_2 / ethics; criteria x3


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()


def _raw_report(**answer):
    a = {"question_turn": 1, "question": "Clinical scenario: chest pain", "category": "clinical", "answer_summary": "s",
         "scores": {"clinical_knowledge": 4, "communication": 2, "insight": 3, "relevance": 5},
         "better_answer": "b", "tips": ["t"], "station": "ethics"}
    a.update(answer)
    return {"summary": "ok", "answers": [a], "top_fixes": ["a", "b", "c"]}


TURNS = [{"idx": 0, "speaker": "interviewer", "text": "Q"}, {"idx": 1, "speaker": "candidate", "text": "A, um, yes"}]


def test_resolve_category_allowed():
    assert resolve_category("intro", "x") == "intro"
    assert resolve_category("bogus", "Tell me about yourself") == "intro"
    assert resolve_category("bogus", "Tell me about yourself", ("clinical", "other")) == "other"
    assert resolve_category("Clinical", "x", ("clinical", "other")) == "clinical"


def test_normalise_with_brief():
    r = feedback.normalise(_raw_report(), TURNS, BRIEF)
    a = r["answers"][0]
    assert list(a["scores"]) == ["clinical_knowledge", "communication", "insight"]
    assert a["average"] == 3.0 and a["category"] == "clinical" and a["station"] == "ethics"
    assert [c["key"] for c in r["criteria"]] == ["clinical_knowledge", "communication", "insight"]
    assert r["criteria_hash"] == brief.criteria_hash(BRIEF["criteria"])
    assert [c["key"] for c in r["categories"]] == ["clinical", "ethics", "other"]
    assert "station" not in feedback.normalise(_raw_report(station="nope"), TURNS, BRIEF)["answers"][0]


def test_normalise_default_stamps_default_rubric():
    r = feedback.normalise(_raw_report(category="behavioural", scores={"relevance": 3}), TURNS)
    assert list(r["answers"][0]["scores"]) == list(feedback.CRITERIA)
    assert "station" not in r["answers"][0]
    assert r["criteria_hash"] == brief.DEFAULT_CRITERIA_HASH and len(r["categories"]) == 8


def test_report_schema_from_brief():
    s = feedback.report_schema(BRIEF)
    ans = s["properties"]["answers"]["items"]
    assert ans["properties"]["category"]["enum"] == ["clinical", "ethics", "other"]
    assert ans["properties"]["scores"]["required"] == ["clinical_knowledge", "communication", "insight"]
    assert ans["properties"]["station"]["enum"] == ["clinical_scenario", "clinical_scenario_2", "ethics"]
    assert feedback.report_schema(None) == feedback.REPORT_SCHEMA
    assert drill.schema(BRIEF)["properties"]["scores"]["required"] == ["clinical_knowledge", "communication", "insight"]


def test_report_rubric_defaults_for_old_reports():
    rub = brief.report_rubric({"answers": []})
    assert [c["key"] for c in rub["criteria"]] == list(feedback.CRITERIA)
    assert rub["criteria_hash"] == brief.DEFAULT_CRITERIA_HASH
    assert brief.targets(rub["categories"]) == delivery.TARGET_SECONDS


def test_prompts_with_a_brief_never_read_the_materials():
    pack = {"role": "R", "jd": "SECRET-JD", "profile": "SECRET-CV", "company_notes": "SECRET-NOTES"}
    for text in (feedback._system_prompt(pack, None, BRIEF), drill.system_prompt(pack, BRIEF)):
        assert "SECRET" not in text
        assert "f" in text and "Candidate facts" in text  # candidate_facts "f"
        assert '"clinical_knowledge": 3' in text and "three criteria" in text
    text = feedback._system_prompt(pack, None, BRIEF)
    assert "one entry in \"answers\" per STATION" in text and "ethics = Ethics" in text
    assert '"station": "station key"' in text


def test_entries_rule_conversation_flags():
    conv = brief.clean_brief(_raw(format={"kind": "conversation", "opening": False, "candidate_questions": False}))
    rule = brief.entries_rule(conv)
    assert "tell me about yourself" not in rule and "questions the candidate asked" not in rule
    assert brief.entries_rule(None).startswith('- Make one entry in "answers" per MAIN question')


def test_markdown_uses_report_criteria():
    r = feedback.normalise(_raw_report(), TURNS, BRIEF)
    md = feedback.to_markdown(r, {"title": "T"}, {"started_at": 0})
    assert "Clinical Knowledge 4/5 · communication 2/5 · Insight 3/5 (average 3.0)" in md


def test_delivery_targets_from_categories():
    answers = [{"question_turn": 0, "category": "ethics"}]
    turns = [{"idx": 1, "speaker": "candidate", "text": "word " * 50, "t_start_ms": 0, "t_end_ms": 30000}]
    delivery.answer_delivery(answers, turns, targets=brief.targets(BRIEF["categories"]))
    assert answers[0]["delivery"]["target"] == [60, 120] and answers[0]["delivery"]["flag"] == "short"


def test_session_snapshot_and_history_with_other_criteria(tmp_db):
    pack = db.create_pack({"title": "t", "jd": "x"})
    sid = db.create_session(pack["id"], BRIEF)
    assert feedback.session_brief(db.get_session(sid)) == BRIEF
    assert feedback.session_brief(db.get_session(db.create_session(pack["id"]))) is None
    report = feedback.normalise(_raw_report(), TURNS, BRIEF)
    db.set_report_pending(sid)
    db.save_report(sid, report, "")
    db.end_session(sid)
    summary = next(s for s in db.pack_history(pack["id"]) if s["id"] == sid)  # no KeyError on other criteria
    assert summary["criteria"] == {"clinical_knowledge": 4, "communication": 2, "insight": 3}
    assert summary["criteria_hash"] == brief.criteria_hash(BRIEF["criteria"])
    assert summary["criteria_names"]["insight"] == "Insight" and summary["category_labels"]["ethics"] == "Ethics"
    assert summary["by_category"] == {"clinical": {"average": 3.0, "answers": 1}}
    assert db.get_report(sid)["report"]["answers"][0]["category"] == "clinical"
    assert db.frozen_rubric(pack["id"]) == brief.rubric_of(BRIEF)


def test_old_report_summary_unchanged(tmp_db):
    pack = db.create_pack({"title": "t", "jd": "x"})
    sid = db.create_session(pack["id"])
    old = {"answers": [{"question": "Tell me about yourself", "scores": {c: 3 for c in feedback.CRITERIA}, "average": 3.0}]}
    db.set_report_pending(sid)
    with db.connect() as conn:
        conn.execute("UPDATE reports SET report_json = ?, status = 'ready' WHERE session_id = ?", (json.dumps(old), sid))
    db.end_session(sid)
    s = db.pack_history(pack["id"])[0]
    assert s["criteria"] == {c: 3 for c in feedback.CRITERIA}
    assert s["criteria_hash"] == brief.DEFAULT_CRITERIA_HASH
    assert s["by_category"] == {"intro": {"average": 3.0, "answers": 1}}


def test_drill_result_carries_rubric():
    res = drill.build_result({"scores": {"insight": 5}}, "an answer", 12.0, BRIEF)
    assert list(res["scores"]) == ["clinical_knowledge", "communication", "insight"]
    assert res["criteria_hash"] == brief.criteria_hash(BRIEF["criteria"]) and res["criteria"][2]["name"] == "Insight"
    assert drill.build_result({"scores": {}}, "a", None)["criteria_hash"] == brief.DEFAULT_CRITERIA_HASH


def test_frontend_knows_the_default_criteria_hash():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert f"export const DEFAULT_CRITERIA_HASH = '{brief.DEFAULT_CRITERIA_HASH}'" in api
