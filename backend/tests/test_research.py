from backend import research


def test_build_prompt_includes_company_role_and_truncates_jd():
    p = research.build_prompt(" Contoso ", "SE", "Q" * 5000)
    assert "Company: Contoso" in p and "applying for: SE" in p
    assert p.count("Q") == research.MAX_JD_CHARS


def test_build_prompt_company_only():
    assert research.build_prompt("Contoso") == "Company: Contoso"


def test_parse_reply_notes_and_sources():
    reply = "NOTES:\nContoso sells widgets.\n- Raised funds (May 2025)\n\nSOURCES:\n- https://a.com/x\n- https://b.com/y.\n- https://a.com/x\n"
    notes, sources = research.parse_reply(reply)
    assert notes == "Contoso sells widgets.\n- Raised funds (May 2025)"
    assert sources == ["https://a.com/x", "https://b.com/y"]


def test_parse_reply_without_markers():
    notes, sources = research.parse_reply("Just some notes.")
    assert notes == "Just some notes." and sources == []


def test_parse_reply_bold_markers():
    notes, sources = research.parse_reply("**NOTES:** hello\n\n**Sources:**\n1. https://a.com")
    assert notes == "hello" and sources == ["https://a.com"]
