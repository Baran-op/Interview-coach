"""V6: voice evidence in the report request, advice cleaning, stored sections (PLAN-voice.md)."""

import wave

import numpy as np

from backend import delivery, feedback, voice
from backend.tests.golden.fixtures import VOICE_EVIDENCE
from backend.tests.test_delivery_audio import _RATE, _speech, _tone

TURNS = [
    {"idx": 4, "speaker": "interviewer", "text": "Tell me about a go-live."},
    {"idx": 5, "speaker": "candidate", "text": "So we moved the finance team.", "t_start_ms": 0, "t_end_ms": 78000},
]


def test_transcript_unchanged_without_evidence():
    plain = "[#4 Interviewer] Tell me about a go-live.\n[#5 Candidate, 78 s] So we moved the finance team."
    assert feedback._transcript(TURNS) == plain
    assert feedback._transcript(TURNS, None) == plain
    assert feedback._transcript(TURNS, {}) == plain
    no_adv = {5: {**VOICE_EVIDENCE[5], "sections": [{**VOICE_EVIDENCE[5]["sections"][0], "advice_ok": False}]}}
    assert feedback._transcript(TURNS, no_adv) == plain


def test_evidence_line_format():
    out = feedback._transcript(TURNS, VOICE_EVIDENCE).splitlines()
    assert out[2] == ('  (voice, measured: pitch range 3.1 st, your usual 5.4; flat stretch T5.1 at 0:21-0:33 of this answer, '
                      'range 1.6 st over 12 s, words: "so we moved the finance team onto the new ledger in three weeks and then we")')
    ev = {5: {**VOICE_EVIDENCE[5], "stats": None, "usual": None}}
    assert feedback._transcript(TURNS, ev).splitlines()[2].startswith("  (voice, measured: flat stretch T5.1")


def test_voice_rules_slot():
    pack = {"role": "PM", "company": "Acme"}
    plain = feedback._system_prompt(pack)
    assert "{voice_rules}" not in plain and "(voice, measured:" not in plain
    assert feedback._system_prompt(pack, evidence={}) == plain
    with_rules = feedback._system_prompt(pack, evidence=VOICE_EVIDENCE)
    assert "(voice, measured:" in with_rules and "voice_advice" in with_rules and with_rules != plain
    assert with_rules.replace(voice.rules_text(VOICE_EVIDENCE), "") == plain


def test_schema_with_and_without_voice():
    assert feedback.report_schema(None) == feedback.REPORT_SCHEMA
    item = feedback.report_schema(None, voice=True)["properties"]["answers"]["items"]
    assert item["properties"]["voice_advice"]["items"]["required"] == ["section", "stress", "say_it", "why"]
    assert "voice_advice" not in item["required"]
    assert "voice_advice" not in feedback.REPORT_SCHEMA["properties"]["answers"]["items"]["properties"]


def _raw(advice):
    return {"summary": "s", "top_fixes": ["f"], "answers": [
        {"question_turn": 4, "question": "q", "answer_summary": "a", "scores": {}, "better_answer": "b", "tips": [],
         "voice_advice": advice}]}


def _good(**kw):
    return {"section": "T5.1", "stress": ["three weeks"], "say_it": "We moved finance in THREE WEEKS.",
            "why": "The result got the same pitch as the setup.", **kw}


def test_normalise_keeps_valid_and_drops_the_rest():
    def advice(items):
        return feedback.normalise(_raw(items), TURNS, None, VOICE_EVIDENCE)["answers"][0].get("voice_advice")

    assert advice([_good()]) == [{"section": "T5.1", "stress": ["three weeks"], "say_it": "We moved finance in THREE WEEKS.",
                                  "why": "The result got the same pitch as the setup."}]
    assert advice([_good(stress=["Three, Weeks!"])]) is not None  # casefolded, punctuation stripped
    assert advice([_good(section="T9.1")]) is None  # unknown section
    assert advice([_good(stress=["next quarter"])]) is None  # stress words not in the stretch
    assert advice([_good(why="You sounded nervous here.")]) is None
    assert advice([_good(say_it="Be CONFIDENT about THREE WEEKS")]) is None
    assert advice([_good(stress=[])]) is None
    assert len(advice([_good(say_it="x" * 500, why="y" * 500)])[0]["say_it"]) == 300
    assert advice([_good(), _good()]) and len(advice([_good(), _good()])) == 1
    assert "voice_advice" not in feedback.normalise(_raw([_good()]), TURNS, None, None)["answers"][0]


def test_normalise_only_accepts_sections_of_the_answers_own_turns():
    turns = [*TURNS, {"idx": 6, "speaker": "interviewer", "text": "q2"},
             {"idx": 7, "speaker": "candidate", "text": "b", "t_start_ms": 0, "t_end_ms": 5000}]
    raw = _raw([_good()])
    raw["answers"].append({"question_turn": 6, "question": "q2", "answer_summary": "a", "scores": {}, "better_answer": "b",
                           "tips": [], "voice_advice": [_good()]})
    out = feedback.normalise(raw, turns, None, VOICE_EVIDENCE)["answers"]
    assert out[0]["voice_advice"] and "voice_advice" not in out[1]  # T5.1 belongs to the first answer only


def _write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(_RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def test_turn_evidence_from_a_wav(tmp_path):
    _write_wav(tmp_path / "5.wav", _speech(_tone(2.5, 150), 8))  # 24 s of a steady tone in phrases
    words = [{"w": f"w{i}", "start_ms": i * 400, "end_ms": i * 400 + 300} for i in range(60)]
    turns = [{"idx": 3, "speaker": "interviewer", "text": "q"}, {"idx": 4, "speaker": "candidate", "text": "typed"},
             {"idx": 5, "speaker": "candidate", "text": "spoken", "words": words, "segments": [{"start_ms": 1000, "end_ms": 25000}]}]
    ev = voice.turn_evidence(turns, tmp_path, {"pitch_range_st": 5.0})
    assert set(ev) == {5}  # typed turn (no WAV) and interviewer turn: nothing
    assert ev[5]["usual"] == 5.0 and ev[5]["flags"] == ["flat"]
    (s,) = ev[5]["sections"]
    assert s["id"] == "T5.1" and s["turn_idx"] == 5 and s["advice_ok"] and s["provisional"]
    assert s["session_start_ms"] >= 1000 and 0 < len(s["words"]) <= 40 and s["words"][0].startswith("w")
    # no words: the stretch is kept (drawn) but gets no advice
    ev = voice.turn_evidence([{**turns[2], "words": None}], tmp_path, None)
    assert ev[5]["sections"][0]["advice_ok"] is False
    assert voice.turn_evidence(turns, tmp_path / "missing") == {}


def test_answer_delivery_stores_sections_with_advice(tmp_path):
    answers = [{"question_turn": 4, "category": "other", "voice_advice": [_good()]}]
    _write_wav(tmp_path / "5.wav", _speech(_tone(2.5, 150), 8))
    delivery.answer_delivery(answers, TURNS, tmp_path, evidence=VOICE_EVIDENCE)
    # the fixture's evidence names turn 5 but the WAV is only used for the numbers
    sec = answers[0]["delivery"]["voice"]["sections"]
    assert [s["id"] for s in sec] == ["T5.1"] and sec[0]["advice"]["stress"] == ["three weeks"]
    assert sec[0]["turn_idx"] == 5 and sec[0]["start_ms"] == 21000
    answers = [{"question_turn": 4, "category": "other"}]
    delivery.answer_delivery(answers, TURNS, tmp_path)  # no evidence: today's shape, no sections key
    assert "sections" not in answers[0]["delivery"]["voice"]


def test_markdown_lists_flat_stretches():
    report = {"overall_score": 3, "summary": "s", "top_fixes": ["a"], "filler_words": {"count": 0, "examples": []},
              "avg_answer_seconds": None, "answers": [{"question": "q", "scores": {}, "average": 3, "answer_summary": "a",
                                                       "tips": [], "better_answer": "b",
                                                       "delivery": {"first_answer_seconds": 70, "target": None, "wpm": None, "i_count": 0, "we_count": 0,
                                                                    "numbers": 0, "fillers": 0, "hedges": 0, "voice": {"sections": [{
                                                           **VOICE_EVIDENCE[5]["sections"][0],
                                                           "advice": {"stress": ["three weeks"], "say_it": "In THREE WEEKS.", "why": "w"}}]}}}]}
    md = feedback.to_markdown(report, {}, {"started_at": 0})
    assert "- Flat 0:21–0:33, while saying: “so we moved the finance team onto the new ledger in three weeks and then…”. Stress *three weeks*: “In THREE WEEKS.”" in md
