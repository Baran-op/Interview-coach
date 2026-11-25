"""Materials (PLAN-brief I1): pure helpers, storage, legacy packs and the pack routes."""

import pytest
from fastapi.testclient import TestClient

from backend import brain, db, feedback, main, materials, prep
from backend.tests.golden.fixtures import CONSULTANT


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init()


@pytest.fixture
def client(tmp_db):
    return TestClient(main.app)  # no `with`: the lifespan (model loading) is not run


def _m(name, kind, text, source="paste"):
    return {"name": name, "kind": kind, "source": source, "text": text}


def test_guess_kind():
    assert materials.guess_kind("Sam_Rivera_CV.pdf") == "candidate"
    assert materials.guess_kind("resume-2026.txt") == "candidate"
    assert materials.guess_kind("Mark scheme.pdf") == "format"
    assert materials.guess_kind("Person specification") == "format"
    assert materials.guess_kind("Station brief") == "format"
    assert materials.guess_kind("Job advert") == "job"
    assert materials.guess_kind("Web research: Brightloom") == "organisation"
    assert materials.guess_kind("Notes") == "other"


def test_synthetic_and_slots_match_legacy_fields():
    syn = materials.synthetic(CONSULTANT)
    assert [(m["name"], m["kind"]) for m in syn] == [
        ("Job description", "job"), ("CV", "candidate"), ("Company notes", "organisation")]
    assert all(m["synthetic"] for m in syn)
    slots = materials.legacy_slots(CONSULTANT)
    assert slots == {k: CONSULTANT[k] for k in ("jd", "profile", "company_notes")}
    assert materials.legacy_slots({"jd": "x"}) == {"jd": "x", "profile": "", "company_notes": ""}


def test_slots_from_several_materials_get_headers():
    pack = {"materials": [_m("Advert", "job", "A"), _m("CV", "candidate", "C"), _m("Mark scheme", "format", "M"),
                          _m("Notes", "other", "N")]}
    slots = materials.legacy_slots(pack)
    assert slots["jd"] == "### Advert\nA\n\n### Mark scheme\nM\n\n### Notes\nN"
    assert slots["profile"] == "C" and slots["company_notes"] == ""


def test_stored_materials_render_like_legacy_columns():
    """A legacy pack saved as real materials renders byte-identical prompts."""
    stored = {**CONSULTANT, "jd": None, "profile": None, "company_notes": None,
              "materials": [{**m, "synthetic": False} for m in materials.synthetic(CONSULTANT)]}
    assert brain.build_system_prompt(stored) == brain.build_system_prompt(CONSULTANT)
    assert feedback._system_prompt(stored) == feedback._system_prompt(CONSULTANT)
    assert prep.source_hash(stored) == prep.source_hash(CONSULTANT)


def test_clean():
    out = materials.clean([_m("  Job   advert ", "bogus", "t"), _m("x", "job", "   "), {"text": "y"}])
    assert out == [{"name": "Job advert", "kind": "job", "source": "paste", "text": "t"},
                   {"name": "Notes", "kind": "other", "source": "paste", "text": "y"}]


def test_legacy_pack_and_save_with_materials(tmp_db):
    pack = db.create_pack({"title": "t", "jd": "JD text", "profile": "CV text"})
    assert pack["materials"] == []
    shown = db.pack_materials(pack)
    assert [m["name"] for m in shown] == ["Job description", "CV"] and shown[0]["synthetic"]
    saved = db.update_pack(pack["id"], {"title": "t", "materials": [
        {k: m[k] for k in ("name", "kind", "source", "text")} for m in shown]})
    assert [m["text"] for m in saved["materials"]] == ["JD text", "CV text"]
    assert saved["jd"] == "JD text"  # the old columns are left untouched
    assert materials.legacy_slots(saved)["jd"] == "JD text"
    db.delete_pack(pack["id"])
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 0


def test_routes(client):
    r = client.post("/packs", json={"title": "Doc", "materials": [
        _m("Person specification", "format", "Clinical skills."), _m("CV", "candidate", "FY2 doctor.")]})
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["jd"] is None and [m["kind"] for m in pack["materials"]] == ["format", "candidate"]
    got = client.get(f"/packs/{pack['id']}").json()
    assert got["materials"][1]["text"] == "FY2 doctor."
    assert client.post("/packs", json={"title": "x", "materials": []}).status_code == 422
    assert client.post("/packs", json={"title": "x"}).status_code == 422  # no jd, no materials
    big = "a" * (materials.MAX_PACK_CHARS + 1)
    assert client.put(f"/packs/{pack['id']}", json={"title": "x", "materials": [_m("N", "other", big)]}).status_code == 413
    legacy = client.post("/packs", json={"title": "old", "jd": "JD"}).json()  # an old client
    assert legacy["materials"][0]["synthetic"] is True


def test_extract_text(client):
    files = [("files", ("notes.md", b"# Hello\nworld", "text/markdown")),
             ("files", ("scan.pdf", b"not a pdf", "application/pdf")),
             ("files", ("pic.png", b"\x89PNG", "image/png"))]
    out = client.post("/extract-text", files=files).json()
    assert out[0] == {"name": "notes.md", "chars": 13, "text": "# Hello\nworld"}
    assert "Could not read the PDF" in out[1]["error"]
    assert "Only .pdf" in out[2]["error"]
    single = client.post("/extract-text", files=[("file", ("a.txt", b"hi", "text/plain"))]).json()
    assert single == [{"name": "a.txt", "chars": 2, "text": "hi"}]
