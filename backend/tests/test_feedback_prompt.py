from backend import feedback


def test_company_notes_in_report_prompt():
    text = feedback._system_prompt({"role": "PM", "company": "Acme", "company_notes": "Acme makes anvils."})
    assert "Acme makes anvils." in text
    assert "{company_notes}" not in text


def test_company_notes_missing():
    assert "(not provided)" in feedback._system_prompt({})


def test_probing_instructions_in_both_prompts():
    from backend import brain

    pack = {"role": "PM", "company": "Acme", "jd": "x", "profile": "y"}
    interviewer = brain.build_system_prompt(pack, [])
    assert "sceptical hiring manager" in interviewer
    assert "at least two of them" in interviewer
    assert "Never read the list out" in interviewer
    assert "{history}" not in interviewer and "{company_notes}" not in interviewer
    report = feedback._system_prompt(pack)
    assert "probed a gap" in report
    assert "{previous_fixes}" not in report
