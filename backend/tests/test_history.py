from backend import brain, feedback

HIST = [{
    "started_at": 1700000000000,
    "answers": [
        {"question": "Tell me about a conflict", "category": "behavioural", "average": 2.5},
        {"question": "Why Acme?", "category": "motivation", "average": 4.2},
    ],
    "top_fixes": ["Add numbers to results"],
}]


def test_history_block_first_session():
    assert "first session" in brain.history_block([])
    assert "first session" in brain.history_block(None)


def test_history_block_lists_questions_and_fixes():
    text = brain.history_block(HIST)
    assert "Tell me about a conflict" in text and "(2.5)" in text
    assert "Add numbers to results" in text
    assert "never mention earlier sessions" in text.lower()


def test_interviewer_prompt_has_history():
    assert "Why Acme?" in brain.build_system_prompt({"role": "PM"}, HIST)
    p = brain.build_system_prompt({"role": "PM"})
    assert "first session" in p and "{history}" not in p


def test_report_prompt_has_previous_fixes():
    assert "1. Add numbers to results" in feedback._system_prompt({}, ["Add numbers to results"])
    text = feedback._system_prompt({})
    assert "{previous_fixes}" not in text and "\nnone\n" in text


def _raw(prev):
    a = {"question_turn": 1, "question": "Q", "answer_summary": "s",
         "scores": {c: 3 for c in feedback.CRITERIA}, "better_answer": "b", "tips": []}
    return {"summary": "s", "answers": [a], "top_fixes": ["x"], "previous_fixes": prev}


def test_normalise_statuses():
    prev = [
        {"fix": "a", "status": "Improved", "evidence": "#3"},
        {"fix": "b", "status": "not yet"},
        {"fix": "c", "status": "bogus"},
        {"fix": "d", "status": "partly"},
        {"fix": "e", "status": "partly"},
        {"status": "improved"},
    ]
    out = feedback.normalise(_raw(prev), [])["previous_fixes"]
    assert [p["status"] for p in out] == ["improved", "not_yet", "not_tested"]
    assert feedback.normalise(_raw(None), [])["previous_fixes"] == []


def test_markdown_since_last_time():
    report = feedback.normalise(_raw([{"fix": "a", "status": "improved", "evidence": "#3"}]), [])
    md = feedback.to_markdown(report, {}, {"started_at": 0})
    assert "## Since last time" in md and "✓ Improved" in md
