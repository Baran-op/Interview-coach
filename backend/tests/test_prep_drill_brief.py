"""Prep, Drill starters and target lengths from the brief (PLAN-brief I6)."""

import pytest

from backend import brief, db, delivery, drill, prep
from backend.tests.golden.fixtures import CONSULTANT
from backend.tests.test_brief import _raw

STATIONS = brief.clean_brief(_raw())


def _conv(**fmt):
    return brief.clean_brief(_raw(
        format={"kind": "conversation", "opening": True, "candidate_questions": True, **fmt},
        likely_questions=[{"question": "Walk me through a ward round.", "category": "clinical", "why": "w"},
                          {"question": "Another clinical one?", "category": "clinical", "why": ""},
                          {"question": "A dilemma you faced?", "category": "ethics", "why": ""}],
        competencies=["Clinical judgement", "Teamwork"]))


def test_prep_prompt_from_brief():
    b = _conv()
    text = prep.system_prompt(CONSULTANT, b)
    assert "  - Walk me through a ward round. (clinical)" in text
    assert "Clinical judgement; Teamwork" in text and 'Include "Tell me about yourself"' in text
    assert "an empty list: this interview's answers are not STAR-shaped" in text  # no category hint uses STAR
    assert "4 to 6 sharp questions" in text
    for secret in (CONSULTANT["jd"], CONSULTANT["profile"], CONSULTANT["company_notes"]):
        assert secret not in text
    off = _conv(opening=False, candidate_questions=False)
    text = prep.system_prompt(CONSULTANT, off)
    assert 'Do not include "Tell me about yourself"' in text and "no time for the candidate's questions" in text


def test_stories_only_with_star():
    assert prep.wants_stories(None)
    assert not prep.wants_stories(_conv())
    star = _conv()
    star["categories"][0]["structure_hint"] = "STAR: situation, task, action, result"
    assert prep.wants_stories(star)
    star["categories"][0]["structure_hint"] = "Start with the patient"  # "start" is not STAR
    assert not prep.wants_stories(star)


def test_prep_source_hash_with_brief():
    b = _conv()
    assert prep.source_hash(CONSULTANT) == prep.source_hash(CONSULTANT, None)
    h = prep.source_hash(CONSULTANT, b)
    assert h != prep.source_hash(CONSULTANT)
    edited = {**b, "probes": ["new probe"]}
    assert prep.source_hash(CONSULTANT, edited) != h


def test_clean_sheet_resolves_against_brief_categories():
    sheet = prep.clean_sheet({"likely_questions": [{"question": "Tell me about yourself", "category": "intro"},
                                                   {"question": "Q", "category": "ethics"}]}, ("ethics", "other"))
    assert [q["category"] for q in sheet["likely_questions"]] == ["other", "ethics"]


def test_drill_starters():
    assert [q["source"] for q in drill.starter_questions(CONSULTANT)] == ["starter"] * 5
    qs = drill.starter_questions(CONSULTANT, _conv())
    assert [q["question"] for q in qs] == ["Tell me about yourself.", "Walk me through a ward round.", "A dilemma you faced?"]
    assert qs[0]["category"] == "other"  # the brief has no intro category
    assert {q["source"] for q in qs} == {"brief"}
    assert drill.starter_questions(CONSULTANT, _conv(opening=False))[0]["question"] == "Walk me through a ward round."
    st = drill.starter_questions(CONSULTANT, STATIONS)
    assert [q["question"] for q in st] == ["Clinical scenario: A patient...", "Again: practise this station.", "Ethics: practise this station."]
    assert [q["category"] for q in st] == ["clinical", "other", "ethics"]


def test_drill_length_flag():
    b = _conv()  # ethics: 60-120 s
    res = drill.build_result({"scores": {}}, "answer", 30.0, b, "ethics")
    assert res["delivery"]["target"] == [60, 120] and res["delivery"]["flag"] == "short"
    assert drill.build_result({"scores": {}}, "a", 75.0, None, "intro")["delivery"]["flag"] is None
    assert drill.build_result({"scores": {}}, "a", 200.0, None, "behavioural")["delivery"]["flag"] == "long"
    assert drill.build_result({"scores": {}}, "a", 200.0, None, "technical")["delivery"]["target"] is None


def test_long_scenario_station_has_no_target():
    assert brief.untimed_stations(STATIONS) == {"clinical_scenario"}  # 10 min with a scenario
    answers = [{"question_turn": 0, "category": "clinical", "station": "clinical_scenario"},
               {"question_turn": 2, "category": "ethics", "station": "ethics"}]
    turns = [{"idx": 1, "speaker": "candidate", "text": "a b c", "t_start_ms": 0, "t_end_ms": 5000},
             {"idx": 3, "speaker": "candidate", "text": "a b c", "t_start_ms": 0, "t_end_ms": 5000}]
    targets = {"clinical": (60, 120), "ethics": (60, 120)}
    delivery.answer_delivery(answers, turns, targets=targets, no_target=brief.untimed_stations(STATIONS))
    assert answers[0]["delivery"]["target"] is None and answers[1]["delivery"]["target"] == [60, 120]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()


def test_questions_for_pack_use_the_brief(tmp_db):
    pack = db.create_pack({"title": "t", "jd": "x"})
    assert {q["source"] for q in drill.questions_for_pack(pack)} == {"starter"}
    db.save_brief(pack["id"], STATIONS, "h", "generated")
    assert [q["source"] for q in drill.questions_for_pack(pack)] == ["brief"] * 3
