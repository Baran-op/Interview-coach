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
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from . import materials

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

def length_instruction(opts: dict) -> str:
    minutes = opts.get("minutes")
    if minutes:
        est = max(2, round(minutes / 4))
        return (
            f"The interview should last about {minutes} minutes: plan for around {est} main questions "
            "and start wrapping up when time is nearly over. The candidate's messages may begin with a "
            "time note such as \"(Time: 12 of 20 min used.)\". Use it to pace yourself, but never mention it."
        )
    return f"Ask {opts.get('num_questions') or 5} main questions."


def time_note(opts: dict, started_at_ms: int, now_ms: int) -> str:
    """Prefix for the candidate's message in timed interviews (not stored in the transcript)."""
    minutes = opts.get("minutes")
    if not minutes:
        return ""
    used = max(0, round((now_ms - started_at_ms) / 60000))
    return f"(Time: {used} of {minutes} min used.) "


STAGES = {
    "screen": (
        "This is a first-round screening call with a recruiter, about 15 to 20 minutes. Keep it light. "
        "After the opening and \"tell me about yourself\", cover: motivation, why they are looking to move now, "
        "what they are looking for in their next role, salary expectations, notice period and availability. "
        "Then ask only two or three light competency questions as the main questions, with few follow-ups, "
        "and finish with the candidate's questions. Do not go deep technically."
    ),
    "full": (
        "This is a full interview with the hiring manager. Follow the shape below as written."
    ),
    "final": (
        "This is a final-round conversation with a senior leader or founder. Go deep on motivation and values, "
        "what they would do in their first 90 days, why they should be chosen over the other candidates, and "
        "where they want to be in a few years. Use fewer, broader main questions and push on the reasoning "
        "behind their answers rather than on technical detail."
    ),
}


def stage_block(opts: dict) -> str:
    """Text for the {stage} slot; packs saved before stages existed count as a full interview."""
    return STAGES.get(opts.get("stage") or "full", STAGES["full"])


FIRST_SESSION_NOTE = "(This is the candidate's first session for this role.)"


def history_block(history: list[dict] | None) -> str:
    """Text for the {history} slot: earlier questions with scores and the open fixes."""
    if not history:
        return FIRST_SESSION_NOTE
    lines = [
        "Earlier sessions for this role, newest first. This is background for you only."
    ]
    for i, sess in enumerate(history, 1):
        label = "Last session" if i == 1 else f"{i} sessions ago"
        when = sess.get("started_at")
        if when:
            from datetime import datetime
            label += " (" + datetime.fromtimestamp(when / 1000).strftime("%Y-%m-%d") + ")"
        lines.append(f"{label}, questions with average score out of 5:")
        for a in sess.get("answers") or []:
            lines.append(f"- [{a.get('category', 'other')}] {a.get('question', '')} ({a.get('average')})")
        fixes = sess.get("top_fixes") or []
        if i == 1 and fixes:
            lines.append("Fixes still open from that session:")
            lines += [f"- {f}" for f in fixes]
    lines += [
        "",
        "Use this as follows:",
        "- Still open with \"tell me about yourself\" and the motivation question: they are practised every time.",
        "- In the main questions, re-test the weakest earlier area with a NEW question (not the same wording), "
        "do not repeat a question that scored 4 or more, and prefer requirements from the job description that "
        "no earlier question tested.",
        "- Never mention earlier sessions, scores or fixes out loud.",
    ]
    return "\n".join(lines)


def build_system_prompt(pack: dict, history: list[dict] | None = None) -> str:
    opts = pack.get("options") or {}
    template = (PROMPTS_DIR / "interviewer.txt").read_text(encoding="utf-8")
    slots = materials.legacy_slots(pack)
    values = {
        "interviewer_name": opts.get("interviewer_name") or "Alex",
        "style": opts.get("style") or "neutral",
        "company": pack.get("company") or "the company",
        "role": pack.get("role") or "the role",
        "jd": slots["jd"] or "(not provided)",
        "profile": slots["profile"] or "(not provided)",
        "company_notes": slots["company_notes"] or "(none)",
        "type": opts.get("interview_type") or "mixed",
        "stage": stage_block(opts),
        "history": history_block(history),
        "n": opts.get("num_questions") or 5,
        "difficulty": opts.get("difficulty") or "medium",
        "length": length_instruction(opts),
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
            include_partial_messages=True,  # stream text so TTS can start early
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
                    text, out = item
                    try:
                        await self._ask(client, text, out)
                        out.put_nowait(_DONE)
                    except Exception as exc:  # surface to the waiting request
                        out.put_nowait(exc if isinstance(exc, BrainError) else BrainError(str(exc)))
        except Exception as exc:
            if self._ready and not self._ready.done():
                self._ready.set_exception(BrainError(f"Could not start Claude: {exc}"))
            # Fail anything still queued.
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item:
                    item[1].put_nowait(BrainError(f"Claude session ended: {exc}"))

    @staticmethod
    async def _ask(client: ClaudeSDKClient, text: str, out: asyncio.Queue) -> None:
        """Send one message and put text deltas on `out` as they arrive."""
        await client.query(text)
        streamed = False
        sent_any = False
        async for msg in client.receive_response():
            if isinstance(msg, StreamEvent):
                ev = msg.event or {}
                delta = ev.get("delta") or {}
                if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    if delta.get("text"):
                        streamed = sent_any = True
                        out.put_nowait(delta["text"])
            elif isinstance(msg, AssistantMessage):
                if msg.error:
                    raise BrainError(f"Claude error: {msg.error}")
                if not streamed:  # no partial events: fall back to the full text
                    full = " ".join(b.text.strip() for b in msg.content if isinstance(b, TextBlock) and b.text.strip())
                    if full:
                        sent_any = True
                        out.put_nowait(full)
            elif isinstance(msg, ResultMessage) and msg.is_error:
                raise BrainError(
                    f"Claude returned an error ({msg.result or msg.subtype}). "
                    "If this keeps happening, sign in again with `claude login` "
                    "(or check CLAUDE_CODE_OAUTH_TOKEN in .env, if you use one)."
                )
        if not sent_any:
            raise BrainError("Claude returned an empty reply")

    async def stream(self, text: str) -> AsyncIterator[str]:
        """Send a message; yield the reply's raw text (with tags) as it streams."""
        if self._task is None or self._task.done():
            raise BrainError("Claude session is not running")
        out: asyncio.Queue = asyncio.Queue()
        await self._queue.put((text, out))
        while True:
            item = await out.get()
            if item is _DONE:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def send(self, text: str) -> ParsedReply:
        parts = [d async for d in self.stream(text)]
        return parse_tags("".join(parts))

    async def close(self) -> None:
        if self._task and not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()


_DONE = object()


# --------------------------------------------------------------------------- #
# Sentence splitting for streaming TTS
# --------------------------------------------------------------------------- #

_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*\s+")


class SentenceSplitter:
    """Cut streamed text into sentences so each can be voiced as soon as it ends.

    A sentence ends at . ! ? followed by whitespace (so "3.5" and "e.g." mid-word
    don't split). Expression tags stay at the start of the sentence they precede.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        out = []
        while True:
            m = _SENTENCE_END.search(self._buf)
            if not m:
                break
            chunk, self._buf = self._buf[:m.end()], self._buf[m.end():]
            if chunk.strip():
                out.append(chunk)
        return out

    def flush(self) -> list[str]:
        chunk, self._buf = self._buf, ""
        return [chunk] if chunk.strip() else []
