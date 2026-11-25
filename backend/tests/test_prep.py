"""Tests for the pure parts of the prep sheet. Run from the repo root: pytest backend/tests"""

from backend import db, drill, prep


def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()


def test_source_hash_tracks_sources_only():
    base = {"jd": "JD", "profile": "CV", "company_notes": "notes"}
    h = prep.source_hash(base)
    assert len(h) == 40
    assert h == prep.source_hash({**base, "title": "other", "role": "x"})
    assert h == prep.source_hash({**base, "jd": " JD \n"})
    assert h != prep.source_hash({**base, "profile": "CV2"})
    assert prep.source_hash({"jd": "a", "profile": "", "company_notes": "b"}) != \
        prep.source_hash({"jd": "", "profile": "a", "company_notes": "b"})


def test_clean_sheet_and_drill_questions():
    sheet = prep.clean_sheet({
        "likely_questions": [{"question": " Why Acme? ", "category": "bogus", "why": "fit"}, {"question": ""}, "x"],
        "gaps": [{"requirement": "SQL", "cv_evidence": "", "how_to_address": "say so"}],
        "stories": [{"title": "Migration", "competencies": ["ownership", ""], "situation": "s", "task": "t",
                     "action": "a", "result": "r [x]", "numbers": None}],
        "questions_to_ask": ["One?", " "],
    })
    assert sheet["likely_questions"] == [{"question": "Why Acme?", "category": "other", "why": "fit"}]
    assert sheet["gaps"][0]["cv_evidence"] is None
    assert sheet["stories"][0]["competencies"] == ["ownership"] and sheet["stories"][0]["numbers"] == []
    assert sheet["questions_to_ask"] == ["One?"]
    assert prep.drill_questions(sheet) == [{"question": "Why Acme?", "category": "other", "source": "prep"}]
    assert prep.drill_questions(None) == []


def test_drill_list_includes_prep_questions(tmp_path, monkeypatch):
    _tmp_db(tmp_path, monkeypatch)
    pack = db.create_pack({"title": "t", "company": "Acme"})
    assert not [q for q in drill.questions_for_pack(pack) if q["source"] == "prep"]
    sheet = {"likely_questions": [
        {"question": "Tell me about yourself", "category": "intro", "why": ""},
        {"question": "Describe a SQL migration you led.", "category": "behavioural", "why": ""}]}
    db.save_prep(pack["id"], "h", sheet)
    qs = drill.questions_for_pack(pack)
    assert [q["question"] for q in qs if q["source"] == "prep"] == ["Describe a SQL migration you led."]
    assert len(qs) == 6  # the intro duplicate stays a starter


def test_delete_pack_removes_prep(tmp_path, monkeypatch):
    _tmp_db(tmp_path, monkeypatch)
    pack = db.create_pack({"title": "t"})
    db.save_prep(pack["id"], "h", {"likely_questions": []})
    assert db.get_prep(pack["id"])["source_hash"] == "h"
    db.delete_pack(pack["id"])
    assert db.get_prep(pack["id"]) is None and db.get_pack(pack["id"]) is None
