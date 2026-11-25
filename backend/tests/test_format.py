"""Format from the brief (PLAN-brief I5): conversation flags, stations and panels in the interviewer prompt."""

from backend import brain, brief, feedback
from backend.tests.golden.fixtures import CONSULTANT
from backend.tests.test_brief import _raw

STATIONS = brief.clean_brief(_raw())  # 3 stations: 10 + 60 + 8 = 78 min, opening and candidate questions off
PLAN = [{"key": s["key"], "name": s["name"], "minutes": s["minutes"]} for s in STATIONS["format"]["stations"]]


def test_parse_station_tag():
    p = brain.parse_tags("[station 2] [neutral] Station two: ethics. [curious] What would you do?")
    assert p.station == 2 and p.text == "Station two: ethics. What would you do?"
    assert [e["tag"] for e in p.expressions] == ["neutral", "curious"]
    assert brain.parse_tags("[Station3][smile] Hi.").station == 3
    assert brain.parse_tags("[smile] Hi.").station is None


def test_station_at_and_current_station():
    plan = [{"minutes": 10}, {"minutes": 8}, {"minutes": 12}]
    m = 60000
    assert [brain.station_at(plan, t * m) for t in (0, 9.9, 10, 17.9, 18, 29, 90)] == [0, 0, 1, 1, 2, 2, 2]
    # no tag: from the clock
    assert brain.current_station(plan, 0, 12 * m, None, None) == (1, None)
    # a tag wins, even when the clock disagrees a little
    assert brain.current_station(plan, 0, 19 * m, 1, 9 * m) == (1, 9 * m)
    # a tagged station far over its time gives way to the clock (a missed tag)
    assert brain.current_station(plan, 0, 22 * m, 0, 0) == (2, None)
    assert brain.current_station([], 0, 5 * m, None, None) == (None, None)


def test_time_note_with_stations():
    plan = [{"minutes": 10}, {"minutes": 8}, {"minutes": 12}]
    m = 60000
    assert brain.time_note({}, 0, 18 * m, 1, plan, 11 * m) == "(Time: station 2 of 3, 7 of 8 min used; 18 of 30 min overall.) "
    assert brain.time_note({}, 0, 12 * m, None, plan) == "(Time: station 2 of 3, 2 of 8 min used; 12 of 30 min overall.) "
    assert brain.time_note({"minutes": 20}, 0, 12 * m) == "(Time: 12 of 20 min used.) "
    assert brain.time_note({}, 0, 12 * m) == ""


def test_stations_prompt():
    text = brain.build_system_prompt(CONSULTANT, None, STATIONS)
    assert "3 timed stations, 78 minutes in all" in text
    assert "Station 1: Clinical scenario (10 min, clinical)." in text and "Scenario to read out: A patient..." in text
    assert "[station N]" in text and "[END]" in text
    assert "Tell me about yourself" not in text.replace('Do not ask "tell me about yourself"', "")
    assert "Candidate questions" not in text and "4. Close." in text
    for secret in (CONSULTANT["jd"], CONSULTANT["profile"], CONSULTANT["company_notes"]):
        assert secret not in text  # nothing downstream reads the raw materials
    assert "Interview type:" not in text  # type, stage and question count don't apply


def test_conversation_flags_and_probes():
    conv = brief.clean_brief(_raw(format={"kind": "conversation", "opening": False, "candidate_questions": False},
                                  probes=["Gap in 2023", "No SQL shown"]))
    text = brain.build_system_prompt(CONSULTANT, None, conv)
    assert '"Tell me about yourself."' not in text and "As your first question, ask why" in text
    assert "4. Candidate questions" not in text and "\n4. Close." in text
    assert "Gap in 2023; No SQL shown" in text and "silently note what a sceptical hiring manager" not in text
    assert "Interview type: mixed" in text  # type and stage still apply
    assert "clinical (d), ethics (d) or other" in text
    on = brief.clean_brief(_raw(format={"kind": "conversation"}))
    text = brain.build_system_prompt(CONSULTANT, None, on)
    assert '"Tell me about yourself."' in text and "4. Candidate questions" in text and "\n5. Close." in text
    assert "using the facts about the organisation" in text


def test_panel_prompt():
    panel = brief.clean_brief(_raw(format={"kind": "panel", "panel": [
        {"name": "Dr Shah", "role": "Consultant", "focus": "teaching"},
        {"name": "Ms Lee", "role": "Lay member", "focus": "values"}]}))
    text = brain.build_system_prompt(CONSULTANT, None, panel)
    assert "This is a panel interview. The panel: Dr Shah, Consultant (leads on teaching); Ms Lee" in text
    assert "one voice" in text and '"Ms Lee here, on values..."' in text


def test_transcript_marks_stations():
    turns = [{"idx": 0, "speaker": "interviewer", "text": "Station one.", "station": "clinical"},
             {"idx": 1, "speaker": "candidate", "text": "I would...", "station": "clinical", "t_start_ms": 0, "t_end_ms": 4000},
             {"idx": 2, "speaker": "interviewer", "text": "Hi"}]
    assert feedback._transcript(turns).splitlines() == [
        "[#0 Interviewer, station clinical] Station one.",
        "[#1 Candidate, 4 s, station clinical] I would...",
        "[#2 Interviewer] Hi",
    ]
