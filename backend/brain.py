"""Interviewer brain: one Claude Agent SDK client per interview session.

A ClaudeSDKClient keeps an anyio task group open internally and must not be
used from a different asyncio task than the one that connected it. FastAPI runs
every request in its own task, so each session gets a dedicated worker task
that owns the client; request handlers hand it messages through a queue and
await the reply.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"

EXPRESSION_TAGS = ("neutral", "smile", "thinking", "nod", "curious", "serious")
_TAG_RE = re.compile(r"\[(neutral|smile|thinking|nod|curious|serious|end)\]\s*", re.IGNORECASE)

OPENING_CUE = (
    "(The candidate has just joined the video call. Greet them, introduce yourself "
    "briefly, and ask your first question.)"
)


# --------------------------------------------------------------------------- #
# Expression tags
# --------------------------------------------------------------------------- #

@dataclass
class ParsedReply:
    text: str                       # clean text, safe to show or speak
    expressions: list[dict] = field(default_factory=list)  # [{tag, char_index}]
    is_final: bool = False          # [END] was present


def parse_tags(raw: str) -> ParsedReply:
    """Strip expression tags from a reply.

    Each expression is returned with the index in the clean text where the
    tagged sentence starts. [END] is not an expression: it sets is_final.
    """
    out: list[str] = []
    out_len = 0
    expressions: list[dict] = []
    is_final = False
    pos = 0
    for m in _TAG_RE.finditer(raw):
        chunk = raw[pos:m.start()]
        if out_len == 0:
            chunk = chunk.lstrip()
        out.append(chunk)
        out_len += len(chunk)
        pos = m.end()
        tag = m.group(1).lower()
        if tag == "end":
            is_final = True
        else:
            expressions.append({"tag": tag, "char_index": out_len})
    tail = raw[pos:]
    if out_len == 0:
        tail = tail.lstrip()
    out.append(tail)
    text = "".join(out).rstrip()
    for e in expressions:
        e["char_index"] = min(e["char_index"], len(text))
    return ParsedReply(text=text, expressions=expressions, is_final=is_final)


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

def build_system_prompt(pack: dict) -> str:
    opts = pack.get("options") or {}
    template = (PROMPTS_DIR / "interviewer.txt").read_text(encoding="utf-8")
    values = {
        "interviewer_name": opts.get("interviewer_name") or "Alex",
        "style": opts.get("style") or "neutral",
        "company": pack.get("company") or "the company",
        "role": pack.get("role") or "the role",
        "jd": pack.get("jd") or "(not provided)",
        "profile": pack.get("profile") or "(not provided)",
        "company_notes": pack.get("company_notes") or "(none)",
        "type": opts.get("interview_type") or "mixed",
        "n": opts.get("num_questions") or 5,
        "difficulty": opts.get("difficulty") or "medium",
    }
    # str.format would choke on braces inside a pasted JD, so substitute by name.
    for key, val in values.items():
        template = template.replace("{" + key + "}", str(val))
    return template


# --------------------------------------------------------------------------- #
# Per-session client
# --------------------------------------------------------------------------- #

class BrainError(RuntimeError):
    pass


class InterviewBrain:
    def __init__(self, system_prompt: str):
        self._system_prompt = system_prompt
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            system_prompt=self._system_prompt,
            tools=[],              # no built-in tools at all
            allowed_tools=[],
            max_turns=1,           # one model turn per message
            setting_sources=[],    # ignore ~/.claude settings and CLAUDE.md files
            model=os.environ.get("INTERVIEWER_MODEL") or None,
        )

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run())
        await self._ready

    async def _run(self) -> None:
        try:
            async with ClaudeSDKClient(options=self._options()) as client:
                self._ready.set_result(None)
                while True:
                    item = await self._queue.get()
                    if item is None:
                        break
                    text, fut = item
                    try:
                        reply = await self._ask(client, text)
                        if not fut.done():
                            fut.set_result(reply)
                    except Exception as exc:  # surface to the waiting request
                        if not fut.done():
                            fut.set_exception(exc)
        except Exception as exc:
            if self._ready and not self._ready.done():
                self._ready.set_exception(BrainError(f"Could not start Claude: {exc}"))
            # Fail anything still queued.
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item and not item[1].done():
                    item[1].set_exception(BrainError(f"Claude session ended: {exc}"))

    @staticmethod
    async def _ask(client: ClaudeSDKClient, text: str) -> str:
        await client.query(text)
        parts: list[str] = []
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                if msg.error:
                    raise BrainError(f"Claude error: {msg.error}")
                parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
            elif isinstance(msg, ResultMessage) and msg.is_error:
                raise BrainError(
                    f"Claude returned an error ({msg.result or msg.subtype}). "
                    "If this keeps happening, check CLAUDE_CODE_OAUTH_TOKEN in .env "
                    "(regenerate with `claude setup-token`)."
                )
        reply = " ".join(p.strip() for p in parts if p.strip())
        if not reply:
            raise BrainError("Claude returned an empty reply")
        return reply

    async def send(self, text: str) -> ParsedReply:
        if self._task is None or self._task.done():
            raise BrainError("Claude session is not running")
        fut = asyncio.get_running_loop().create_future()
        await self._queue.put((text, fut))
        raw = await fut
        return parse_tags(raw)

    async def open(self) -> ParsedReply:
        return await self.send(OPENING_CUE)

    async def close(self) -> None:
        if self._task and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()
