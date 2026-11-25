"""Interview brief (PLAN-brief I2): cleaning, hashing, the default brief and the routes."""

import copy

import pytest
from fastapi.testclient import TestClient

from backend import brief, db, main
from backend.tests.golden.make import GOLDEN_DIR


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()


def _crit(key, name=None):
    return {"key": key, "name": name or key, "description": f"rewards {key}",
            "anchors": {"1": "poor", "3": "ok", "5": "great"}, "source": "provided", "scale_note": "1-4 mapped"}


def _raw(**over):
    raw = {
        "field": "Medicine", "role": "ST1", "organisation": "", "level": "Entry",
        "format": {"kind": "stations", "summary": "Three stations.", "total_minutes": 99, "opening": False,
                   "candidate_questions": False, "panel": [{"name": "x"}],
                   "stations": [
                       {"key": "Clinical Scenario!", "name": "Clinical scenario", "minutes": 10, "category": "clinical",
                        "brief": "b", "scenario": "A patient..."},
                       {"key": "clinical scenario", "name": "Again", "minutes": 500, "category": "nope", "brief": "", "scenario": None},
                       {"key": "ethics", "name": "Ethics", "minutes": "8", "category": "ethics", "brief": "", "scenario": ""},
                   ]},
        "criteria": [_crit("Clinical Knowledge"), _crit("communication"), _crit("communication"), _crit("Insight")],
        "categories": [{"key": "clinical", "label": "Clinical", "description": "d", "structure_hint": "", "scoring_note": "",
                        "target_seconds": [120, 60]},
                       {"key": "ethics", "label": "Ethics", "description": "d", "structure_hint": "", "scoring_note": "",
                        "target_seconds": [60, 120]}],
        "competencies": ["a" * 100] + [f"c{i}" for i in range(20)],
        "likely_questions": [{"question": "Q?", "category": "bogus", "why": "w"}],
        "probes": [], "facts": [], "candidate_summary": "s", "candidate_facts": "f",
        "assumptions": [{"section": "format", "text": "3 stations", "question": "Right?"}],
    }
    raw.update(over)
    return raw


def test_clean_brief_stations_slugs_caps():
    b = brief.clean_brief(_raw())
    f = b["format"]
    assert f["kind"] == "stations" and f["panel"] == []
    assert [s["key"] for s in f["stations"]] == ["clinical_scenario", "clinical_scenario_2", "ethics"]
    assert [s["minutes"] for s in f["stations"]] == [10, 60, 8]
    assert f["total_minutes"] == 78  # the sum of the stations, not the 99 given
    assert [s["category"] for s in f["stations"]] == ["clinical", "other", "ethics"]
    assert f["stations"][2]["scenario"] is None
    assert [c["key"] for c in b["categories"]] == ["clinical", "ethics", "other"]  # `other` added
    assert b["categories"][0]["target_seconds"] is None and b["categories"][1]["target_seconds"] == [60, 120]
    assert len(b["competencies"]) == 12 and len(b["competencies"][0]) == 40
    assert b["likely_questions"][0]["category"] == "other"
    assert [c["key"] for c in b["criteria"]] == ["clinical_knowledge", "communication", "insight"]  # duplicate dropped
    assert b["criteria"][0]["scale_note"] == "1-4 mapped"
    assert b["assumptions"][0]["id"] == "a1" and b["assumptions"][0]["confirmed"] is False


def test_clean_brief_too_few_criteria_uses_defaults():
    b = brief.clean_brief(_raw(criteria=[_crit("only"), _crit("Only"), _crit("two")]))
    assert [c["key"] for c in b["criteria"]] == ["relevance", "structure", "specificity", "evidence"]
    assert all(c["source"] == "default" for c in b["criteria"])
    assert any(a["section"] == "criteria" for a in b["assumptions"])


def test_clean_brief_panel_and_conversation_fallbacks():
    b = brief.clean_brief(_raw(format={"kind": "panel", "panel": [{"name": "Dr Shah", "role": "Lead", "focus": "teaching"}]}))
    assert b["format"]["kind"] == "conversation" and b["format"]["panel"] == []
    b = brief.clean_brief(_raw(format={"kind": "panel", "stations": [{"key": "x"}],
                                       "panel": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}, {"name": "E"}]}))
    assert b["format"]["kind"] == "panel" and len(b["format"]["panel"]) == 4 and b["format"]["stations"] == []
    assert brief.clean_brief({})["format"]["kind"] == "conversation"


def test_clean_brief_frozen_keeps_rubric():
    frozen = brief.rubric_of(brief.default_brief())
    b = brief.clean_brief(_raw(), frozen=frozen)
    assert brief.rubric_hash(brief.rubric_of(b)) == brief.rubric_hash(frozen)
    assert any("kept" in a["text"] for a in b["assumptions"])
    assert b["format"]["stations"][0]["category"] == "other"  # resolved against the frozen categories


def test_clean_brief_is_idempotent_on_default():
    d = brief.default_brief({"role": "R", "company": "C", "options": {"minutes": 30}})
    assert brief.clean_brief(copy.deepcopy(d)) == d


def test_source_hash():
    a = [{"kind": "job", "name": "JD", "text": "x"}, {"kind": "candidate", "name": "CV", "text": "y"}]
    h = brief.source_hash(a)
    assert h == brief.source_hash([{**a[0], "text": " x \n"}, a[1]])
    assert h != brief.source_hash(list(reversed(a)))
    assert h != brief.source_hash([{**a[0], "kind": "other"}, a[1]])
    assert h != brief.source_hash([{**a[0], "name": "Advert"}, a[1]])


def test_criteria_hash():
    c = brief.default_criteria()
    assert brief.criteria_hash(c) == brief.DEFAULT_CRITERIA_HASH
    assert brief.criteria_hash([{**c[0], "source": "provided"}] + c[1:]) == brief.DEFAULT_CRITERIA_HASH  # source ignored
    assert brief.criteria_hash([{**c[0], "name": "Fit"}] + c[1:]) != brief.DEFAULT_CRITERIA_HASH


def test_default_brief_matches_todays_prompts():
    d = brief.default_brief({"options": {"minutes": 20}})
    assert d["format"]["total_minutes"] == 20 and d["format"]["opening"] and d["format"]["candidate_questions"]
    criteria_lines = brief.render_criteria(d["criteria"])
    for name in ("consultant-feedback.txt", "consultant-drill.txt"):
        assert criteria_lines in (GOLDEN_DIR / name).read_text(encoding="utf-8")
    feedback = (GOLDEN_DIR / "consultant-feedback.txt").read_text(encoding="utf-8")
    assert f'- "category": {brief.category_sentence(d["categories"])}.' in feedback
    for c in d["categories"]:
        if c["scoring_note"]:
            assert f"- {c['scoring_note']}\n" in feedback
    from backend.delivery import TARGET_SECONDS

    assert {c["key"]: tuple(c["target_seconds"]) for c in d["categories"] if c["target_seconds"]} == TARGET_SECONDS
    from backend.categories import CATEGORIES

    assert tuple(c["key"] for c in d["categories"]) == CATEGORIES


def test_max_size_brief_renders_under_8000_chars():
    big = lambda n: "x" * n  # noqa: E731
    raw = {
        "field": big(500), "role": big(500), "organisation": big(500), "level": big(500),
        "format": {"kind": "conversation", "summary": big(5000)},
        "criteria": [_crit(f"c{i}") for i in range(6)],
        "categories": [{"key": f"k{i}", "label": "L", "description": big(500)} for i in range(12)],
        "competencies": [big(100)] * 20,
        "likely_questions": [{"question": big(1000), "category": "k1", "why": big(1000)}] * 20,
        "probes": [big(1000)] * 20, "facts": [big(1000)] * 20,
        "candidate_summary": big(5000), "candidate_facts": big(9000),
    }
    b = brief.clean_brief(raw)
    assert len(b["categories"]) == 10 and len(b["candidate_facts"]) == 4000
    assert len(brief.render_context(b)) < 8000


def test_system_prompt_has_materials_defaults_and_answers():
    prev = {"assumptions": [{"text": "3 stations of 10 minutes", "question": "Right?", "answer": "Four of 8.", "confirmed": False},
                            {"text": "unanswered", "question": "?", "answer": "", "confirmed": False}]}
    text = brief.system_prompt({"role": "ST1"}, [{"name": "Person spec", "kind": "format", "text": "Domains..."}], prev)
    assert "### Person spec (kind: format)\nDomains..." in text
    assert "The candidate's answer: Four of 8." in text and "unanswered" not in text
    assert '"key": "relevance"' in text
    assert "{" + "materials}" not in text and "{" + "answers}" not in text


def test_routes(tmp_db, monkeypatch):
    client = TestClient(main.app)
    pack = client.post("/packs", json={"title": "Doc", "materials": [
        {"name": "Mark scheme", "kind": "format", "source": "paste", "text": "Domains"},
        {"name": "CV", "kind": "candidate", "source": "paste", "text": "FY2"}]}).json()
    pid = pack["id"]
    assert pack["brief_meta"]["exists"] is False
    got = client.get(f"/packs/{pid}/brief").json()
    assert got["is_default"] and got["origin"] == "standard" and not got["frozen"]

    seen = {}

    async def fake_write(p, mats, previous, frozen):
        seen.update(previous=previous, frozen=frozen)
        return brief.clean_brief(_raw())

    monkeypatch.setattr(brief, "write", fake_write)
    got = client.post(f"/packs/{pid}/brief", json={}).json()
    assert not got["is_default"] and got["origin"] == "generated" and not got["stale"]
    meta = client.get(f"/packs/{pid}").json()["brief_meta"]
    assert meta["kind"] == "stations" and meta["total_minutes"] == 78 and meta["to_confirm"] == 1

    edited = got["brief"]
    edited["assumptions"][0].update(answer="Yes", confirmed=True)
    got = client.put(f"/packs/{pid}/brief", json={"brief": edited}).json()
    assert got["origin"] == "edited" and got["brief"]["assumptions"][0]["confirmed"]
    client.post(f"/packs/{pid}/brief", json={})
    assert seen["previous"]["assumptions"][0]["answer"] == "Yes" and seen["frozen"] is None

    # materials change -> stale
    client.put(f"/packs/{pid}", json={"title": "Doc", "materials": [
        {"name": "CV", "kind": "candidate", "source": "paste", "text": "FY2, now ST1"}]})
    assert client.get(f"/packs/{pid}/brief").json()["stale"]

    # a scored session freezes the rubric
    sid = db.create_session(pid)
    db.set_report_pending(sid)
    db.save_report(sid, {"answers": []}, "")
    got = client.get(f"/packs/{pid}/brief").json()
    assert got["frozen"] and got["scored_sessions"] == 1
    changed = copy.deepcopy(got["brief"])
    changed["criteria"][0]["name"] = "Something else"
    r = client.put(f"/packs/{pid}/brief", json={"brief": changed})
    assert r.status_code == 409 and "1 scored session" in r.json()["detail"]
    assert client.put(f"/packs/{pid}/brief", json={"brief": changed, "fresh_start": True}).status_code == 200
    client.post(f"/packs/{pid}/brief", json={})
    assert seen["frozen"] is not None  # the session ran with the default brief (no snapshot)
    client.post(f"/packs/{pid}/brief", json={"replace_criteria": True})
    assert seen["frozen"] is None

    got = client.delete(f"/packs/{pid}/brief").json()
    assert got["is_default"]
    client.delete(f"/packs/{pid}")
    assert db.get_brief(pid) is None
