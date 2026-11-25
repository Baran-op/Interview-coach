from backend import stt


def test_sentence_start_words_dropped():
    jd = "Strong communicator wanted. Experience with Salesforce.\n- Manage clients\nOwn onboarding. Build things."
    terms = stt.extract_terms(jd)
    for w in ("Strong", "Experience", "Manage", "Own", "Build"):
        assert w not in terms
    assert "Salesforce" in terms


def test_acronyms_and_digits_kept_at_sentence_start():
    terms = stt.extract_terms("SQL is required. Dynamics 365 helps.")
    assert "SQL" in terms
    assert "Dynamics 365" in terms


def test_two_word_names_kept():
    terms = stt.extract_terms("We use Power BI and Customer Success playbooks.")
    assert "Power BI" in terms
    assert "Customer Success" in terms


def test_cv_terms_first_and_dedup():
    p = stt.keyword_prompt("Consultant", "Acme", ["Worked at Globex on Tableau.", "We use Snowflake and Tableau."])
    topics = p.split("Topics: ")[1]
    assert topics.index("Globex") < topics.index("Snowflake")
    assert topics.lower().count("tableau") == 1


def test_cap_holds_and_filler_seed_kept():
    jd = " ".join(f"and Tool{i}Zed" for i in range(500))
    p = stt.keyword_prompt("Role", "Co", [jd])
    assert p.startswith("Umm, let me think")
    assert len(p) <= stt.MAX_PROMPT_CHARS + 50
    assert "Tool0Zed" in p


def test_hint_order_from_materials():
    from backend import materials

    legacy = {"jd": "We use Snowflake.", "profile": "Worked at Globex.", "company_notes": "Founded in Leeds by Ravelin."}
    assert materials.hint_texts(legacy) == ["Worked at Globex.", "We use Snowflake.", "Founded in Leeds by Ravelin."]
    pack = {"materials": [
        {"name": "Notes", "kind": "other", "text": "Other Zed"},
        {"name": "Advert", "kind": "job", "text": "Job Zed"},
        {"name": "Mark scheme", "kind": "format", "text": "Format Zed"},
        {"name": "CV", "kind": "candidate", "text": "Me Zed"},
    ]}
    assert materials.hint_texts(pack) == ["Me Zed", "Job Zed", "Format Zed", "Other Zed"]
    topics = stt.keyword_prompt("R", "C", materials.hint_texts(legacy)).split("Topics: ")[1]
    assert topics.index("Globex") < topics.index("Snowflake") < topics.index("Ravelin")
