"""Fictional packs for the golden prompt tests. Everything here is invented."""

from __future__ import annotations

CONSULTANT = {
    "id": "golden-consultant",
    "title": "Implementation Consultant @ Brightloom",
    "role": "Implementation Consultant",
    "company": "Brightloom",
    "jd": (
        "Brightloom is hiring an Implementation Consultant to onboard mid-size retailers onto our "
        "inventory platform.\n\n- Run discovery workshops with client stakeholders\n- Configure "
        "integrations (REST APIs, SFTP) and own the go-live plan\n- Train client teams and write "
        "clear runbooks\n- 3+ years in a client-facing SaaS role; SQL a plus"
    ),
    "profile": (
        "Sam Rivera\nImplementation Specialist, Tallyway (2021-present)\n- Led 14 onboarding projects "
        "for wholesale clients, average go-live 9 weeks\n- Built SQL checks that cut data-migration "
        "defects by 30%\nSupport Analyst, Fernbank Logistics (2019-2021)\n- Handled 40 tickets a week, "
        "wrote the internal Jira triage guide"
    ),
    "company_notes": "Brightloom: founded 2016 in Leeds, 220 staff. Values: clarity, ownership, kindness.",
    "options": {"interview_type": "mixed", "stage": "full", "num_questions": 5, "minutes": None,
                "difficulty": "medium", "style": "neutral", "interviewer_name": "Alex", "voice": "af_heart"},
}

ANALYST = {
    "id": "golden-analyst",
    "title": "Product Analyst @ Quillmark",
    "role": "Product Analyst",
    "company": "Quillmark",
    "jd": "Quillmark (note-taking app) wants a Product Analyst: define metrics, run A/B tests, Python and {curly} SQL.",
    "profile": "Jo Okafor. Data Analyst at Pebblepath (2022-now): built the retention dashboard in Looker.",
    "company_notes": "",
    "options": {"interview_type": "behavioural", "stage": "screen", "num_questions": 4, "minutes": None,
                "difficulty": "hard", "style": "tough", "interviewer_name": "Priya", "voice": "bf_emma"},
}

PACKS = {"consultant": CONSULTANT, "analyst": ANALYST}

# 2026-03-02 12:00 UTC: the same calendar date in nearly every timezone.
HISTORY = [
    {
        "started_at": 1772452800000,
        "answers": [
            {"question": "Tell me about yourself.", "category": "intro", "average": 3.0},
            {"question": "Describe a go-live that slipped.", "category": "behavioural", "average": 2.3},
            {"question": "How would you load a CSV of SKUs over SFTP?", "category": "technical", "average": 4.0},
        ],
        "top_fixes": ["Lead with the result.", "Say 'I' not 'we'.", "Quantify the outcome."],
    },
    {
        "started_at": 1771848000000,
        "answers": [{"question": "Why Brightloom?", "category": "motivation", "average": 2.8}],
        "top_fixes": ["Research the company."],
    },
]

FIXES = ["Lead with the result.", "Say 'I' not 'we'.", "Quantify the outcome."]
