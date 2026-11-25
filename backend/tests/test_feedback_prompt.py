from backend import feedback


def test_company_notes_in_report_prompt():
    text = feedback._system_prompt({"role": "PM", "company": "Acme", "company_notes": "Acme makes anvils."})
    assert "Acme makes anvils." in text
    assert "{company_notes}" not in text


def test_company_notes_missing():
    assert "(not provided)" in feedback._system_prompt({})
