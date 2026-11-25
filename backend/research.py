"""Draft company notes from the web (PLAN.md 6b).

One Agent SDK query() with WebSearch/WebFetch. Only this call gets web tools; the interviewer stays
tool-less. Pure helpers (prompt building, reply parsing) are unit-tested; the route lives in main.py.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

log = logging.getLogger("interview-coach.research")
PROMPTS_DIR = Path(__file__).parent / "prompts"
WEB_TOOLS = ["WebSearch", "WebFetch"]
MAX_TURNS = 10
MAX_JD_CHARS = 3000

_URL_RE = re.compile(r"https?://[^\s<>\")\]]+")


class ResearchError(RuntimeError):
    pass


def build_prompt(company: str, role: str = "", jd: str = "") -> str:
    parts = [f"Company: {company.strip()}"]
    if role.strip():
        parts.append(f"Role the candidate is applying for: {role.strip()}")
    jd = (jd or "").strip()
    if jd:
        parts.append("Job description (for context on the team; may be truncated):\n" + jd[:MAX_JD_CHARS])
    return "\n\n".join(parts)


def parse_reply(text: str) -> tuple[str, list[str]]:
    """Split a reply into (notes, sources). Tolerates a missing NOTES:/SOURCES: marker."""
    text = (text or "").strip()
    m = re.search(r"^\W*SOURCES?\W*:?\W*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        body, src_text = text[:m.start()], text[m.end():]
    else:
        body, src_text = text, ""
    body = re.sub(r"^\W*NOTES\W*:\W*", "", body.strip(), flags=re.IGNORECASE).strip()
    sources: list[str] = []
    for url in _URL_RE.findall(src_text):
        url = url.rstrip(".,;")
        if url not in sources:
            sources.append(url)
    return body, sources


async def research_company(company: str, role: str = "", jd: str = "", model: str | None = None) -> dict:
    if not company.strip():
        raise ResearchError("A company name is required")
    options = ClaudeAgentOptions(
        system_prompt=(PROMPTS_DIR / "research.txt").read_text(encoding="utf-8"),
        tools=WEB_TOOLS,
        allowed_tools=WEB_TOOLS,
        max_turns=MAX_TURNS,
        setting_sources=[],
        model=model or os.getenv("RESEARCH_MODEL") or None,
    )
    last_text = ""
    result_text = ""
    try:
        async for msg in query(prompt=build_prompt(company, role, jd), options=options):
            if isinstance(msg, AssistantMessage):
                if msg.error:
                    raise ResearchError(f"Claude error: {msg.error}")
                t = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
                if t.strip():
                    last_text = t
            elif isinstance(msg, ResultMessage):
                if msg.is_error:
                    raise ResearchError(f"Claude returned an error ({msg.result or msg.subtype})")
                result_text = msg.result or ""
    except ResearchError:
        raise
    except Exception as exc:
        raise ResearchError(f"{type(exc).__name__}: {exc}") from exc
    notes, sources = parse_reply(result_text or last_text)
    if not notes:
        raise ResearchError("Claude returned no notes")
    return {"notes": notes, "sources": sources}
