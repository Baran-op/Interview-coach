"""One place to get JSON out of Claude (feedback report now, drill scoring and prep sheet later).

Uses the Agent SDK's `output_format` json_schema, read back from
`ResultMessage.structured_output`. If that is missing the reply text is parsed as free JSON.

The SDK delivers structured output through a `StructuredOutput` tool call it validates against
the schema; a rejected call is retried in another model turn. So `max_turns` must leave room for
retries (with 1, any rejection ended as `error_max_turns`). If the turns still run out, the last
`StructuredOutput` attempt (or the reply text) is used: every caller cleans what it gets anyway.
"""

from __future__ import annotations

import json
import re

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock, query

MAX_TURNS = 4  # first try + up to 3 schema retries


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
        max_turns=MAX_TURNS,
        setting_sources=[],
        model=model or None,
        output_format={"type": "json_schema", "schema": schema},
    )
    parts: list[str] = []
    structured = None
    attempt = None  # input of the last StructuredOutput tool call, valid or not
    error = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            if msg.error:
                raise ClaudeJSONError(f"Claude error: {msg.error}")
            for b in msg.content:
                if isinstance(b, TextBlock):
                    parts.append(b.text)
                elif isinstance(b, ToolUseBlock) and b.name == "StructuredOutput" and isinstance(b.input, dict):
                    attempt = b.input
        elif isinstance(msg, ResultMessage):
            if msg.is_error:
                error = f"Claude returned an error ({msg.result or msg.subtype})"
            structured = msg.structured_output
    return pick_result(structured, attempt, "".join(parts), error)


def pick_result(structured, attempt, text: str, error: str | None) -> dict:
    """Best JSON from one run: validated output, else the last attempt, else the reply text."""
    if isinstance(structured, dict) and structured:
        return structured
    if attempt:
        return attempt
    try:
        return extract_json(text)
    except ClaudeJSONError:
        if error:
            raise ClaudeJSONError(error) from None
        raise
