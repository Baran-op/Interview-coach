"""One place to get JSON out of Claude (feedback report now, drill scoring and prep sheet later).

Uses the Agent SDK's `output_format` json_schema, read back from
`ResultMessage.structured_output`. If that is missing the reply text is parsed as free JSON.
"""

from __future__ import annotations

import json
import re

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query


class ClaudeJSONError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Parse a JSON object out of free text (tolerates code fences and surrounding prose)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ClaudeJSONError("Claude did not return JSON")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ClaudeJSONError(f"Claude returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ClaudeJSONError("Claude did not return a JSON object")
    return data


async def ask_json(system_prompt: str, prompt: str, schema: dict, model: str | None = None) -> dict:
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        tools=[],
        allowed_tools=[],
        max_turns=1,
        setting_sources=[],
        model=model or None,
        output_format={"type": "json_schema", "schema": schema},
    )
    parts: list[str] = []
    structured = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            if msg.error:
                raise ClaudeJSONError(f"Claude error: {msg.error}")
            parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                raise ClaudeJSONError(f"Claude returned an error ({msg.result or msg.subtype})")
            structured = msg.structured_output
    if isinstance(structured, dict) and structured:
        return structured
    return extract_json("".join(parts))
