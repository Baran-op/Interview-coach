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
_TAG_RE = re.compile(r"\[(neutral|smile|thinking|nod|curious|serious|end|station\s*(\d{1,2}))\]\s*", re.IGNORECASE)

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
    station: int | None = None      # [station N]: the interviewer opened station N (1-based)


def parse_tags(raw: str) -> ParsedReply:
    """Strip expression tags from a reply.

    Each expression is returned with the index in the clean text where the
    tagged sentence starts. [END] is not an expression: it sets is_final.
    """
    out: list[str] = []
    out_len = 0
    expressions: list[dict] = []
    is_final = False
    station = None
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
        elif m.group(2):
            station = int(m.group(2))
        else:
            expressions.append({"tag": tag, "char_index": out_len})
    tail = raw[pos:]
    if out_len == 0:
        tail = tail.lstrip()
    out.append(tail)
    text = "".join(out).rstrip()
    for e in expressions:
        e["char_index"] = min(e["char_index"], len(text))
    return ParsedReply(text=text, expressions=expressions, is_final=is_final, station=station)


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


def station_at(plan: list[dict], elapsed_ms: int) -> int:
    """The station (0-based) the clock says is running: each lasts its `minutes`, the last one runs on."""
    end = 0
    for i, st in enumerate(plan):
        end += st["minutes"] * 60000
        if elapsed_ms < end:
            return i
    return max(0, len(plan) - 1)


OVERRUN_MS = 2 * 60000  # a tagged station this far past its time gives way to the clock


def current_station(plan: list[dict], started_at_ms: int, now_ms: int, tagged: int | None,
                    tagged_at_ms: int | None) -> tuple[int | None, int | None]:
    """(running station, its start or None when inferred). The interviewer's last [station N] tag wins,
    unless it has overrun its time by 2+ minutes and the clock says a later station is due (a missed tag)."""
    if not plan:
        return None, None
    inferred = station_at(plan, now_ms - started_at_ms)
    if tagged is None or tagged_at_ms is None:
        return inferred, None
    overran = now_ms - tagged_at_ms > plan[tagged]["minutes"] * 60000 + OVERRUN_MS
    return (inferred, None) if overran and inferred > tagged else (tagged, tagged_at_ms)


def time_note(opts: dict, started_at_ms: int, now_ms: int, station: int | None = None,
              plan: list[dict] | None = None, station_started_ms: int | None = None) -> str:
    """Prefix for the candidate's message in timed interviews (not stored in the transcript).

    With a stations `plan` ([{minutes}]): "(Time: station 2 of 3, 7 of 8 min used; 18 of 30 min overall.) ".
    `station` (0-based) comes from the interviewer's last [station N] tag, started at `station_started_ms`;
    without a tag the station is inferred from the clock.
    """
    elapsed = max(0, now_ms - started_at_ms)
    if plan:
        total = sum(st["minutes"] for st in plan)
        if station is None or not 0 <= station < len(plan) or station_started_ms is None:
            station = station_at(plan, elapsed)
            station_started_ms = started_at_ms + sum(st["minutes"] for st in plan[:station]) * 60000
        used = max(0, round((now_ms - station_started_ms) / 60000))
        return (f"(Time: station {station + 1} of {len(plan)}, {used} of {plan[station]['minutes']} min used; "
                f"{round(elapsed / 60000)} of {total} min overall.) ")
    minutes = opts.get("minutes")
    if not minutes:
        return ""
    used = max(0, round(elapsed / 60000))
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


_SLOT_RE = re.compile(r"\{([a-z_]+)\}")


def _fill(template: str, values: dict) -> str:
    """Substitute {name} slots in one pass (str.format would choke on braces inside a pasted JD, and a
    value is never scanned again for slots)."""
    return _SLOT_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


DEFAULT_CATEGORY_LIST = (
    "The report files each main question under one category: intro, motivation, behavioural, technical, case, "
    "roleplay (you play a client or stakeholder), logistics (notice period, salary, availability) or other. "
    "Keep each question clearly within one of them.")
DEFAULT_PROBE_RULE = (
    "Before you start, silently note what a sceptical hiring manager would probe when comparing this CV with this "
    "job: career or industry switches, short tenures or gaps, requirements the CV does not show, and claims without "
    "numbers. Ask about at least two of them during the main questions, politely but directly (for example, \"I see "
    "you moved from retail into software, what drove that?\"). Never read the list out.")
CANDIDATE_QUESTIONS_STEP = (
    "4. Candidate questions. When the main questions are done, thank them and ask whether they have any questions "
    "for you. Answer briefly and realistically, using the {notes}, and do not make up specific facts such as salary "
    "or team size.\n")


def _category_list(brief: dict | None) -> str:
    if brief is None:
        return DEFAULT_CATEGORY_LIST
    parts = [f"{c['key']} ({c['description']})" if c["description"] else c["key"] for c in brief["categories"]]
    return ("The report files each main question under one category: " + ", ".join(parts[:-1]) + " or " + parts[-1]
            + ". Keep each question clearly within one of them.")


def _probe_rule(brief: dict | None) -> str:
    if not brief or not brief["probes"]:
        return DEFAULT_PROBE_RULE
    return ("These are the points a sceptical interviewer would probe for this candidate: " + "; ".join(brief["probes"])
            + ". Ask about at least two of them during the main questions, politely but directly. Never read the list out.")


def _panel_block(brief: dict | None) -> str:
    panel = (brief or {}).get("format", {}).get("panel") or []
    if not panel:
        return ""
    members = "; ".join(f"{p['name']}" + (f", {p['role']}" if p["role"] else "") + (f" (leads on {p['focus']})" if p["focus"] else "")
                        for p in panel)
    return ("\n\nThis is a panel interview. The panel: " + members + ". You speak for every member, in one voice. In the "
            "opening, introduce the panel by name and role. In the main questions, each member leads the questions in "
            "their own focus area: hand over in speech when the speaker changes and start with their name (for example, "
            f"\"{panel[1]['name']} here, on {panel[1]['focus'] or 'my area'}...\"). Keep it clear who is asking, and keep "
            "one question at a time.")


def conversation_script(opts: dict, brief: dict | None, company: str) -> str:
    """Today's five steps (the default brief renders them word for word), adjusted by a brief's flags."""
    f = (brief or {}).get("format") or {"opening": True, "candidate_questions": True}
    asks = f["candidate_questions"]
    values = {
        "type": opts.get("interview_type") or "mixed",
        "difficulty": opts.get("difficulty") or "medium",
        "length": length_instruction(opts),
        "stage": stage_block(opts),
        "company": company,
        "opening": ' Then ask your first question: "Tell me about yourself."' if f["opening"] else "",
        "motivation_lead": "After their answer, ask" if f["opening"] else "As your first question, ask",
        "category_list": _category_list(brief),
        "probe_rule": _probe_rule(brief),
        "candidate_questions": CANDIDATE_QUESTIONS_STEP.replace(
            "{notes}", "company notes" if brief is None else "facts about the organisation") if asks else "",
        "close_n": 5 if asks else 4,
        "panel": _panel_block(brief),
    }
    return _fill((PROMPTS_DIR / "script_conversation.txt").read_text(encoding="utf-8").rstrip("\n"), values)


def stations_script(opts: dict, brief: dict) -> str:
    f = brief["format"]
    lines = []
    for i, st in enumerate(f["stations"], 1):
        line = f"Station {i}: {st['name']} ({st['minutes']} min, {st['category']})."
        if st["brief"]:
            line += f" What it tests and how it runs: {st['brief']}"
        if st["scenario"]:
            line += f"\n   Scenario to read out: {st['scenario']}"
        lines.append(line)
    asks = f["candidate_questions"]
    values = {
        "summary": f["summary"] or "a station-based interview.",
        "difficulty": opts.get("difficulty") or "medium",
        "n_stations": len(f["stations"]),
        "total_minutes": f["total_minutes"],
        "stations": "\n".join(lines),
        "candidate_questions": ("4. Candidate questions. After the last station, ask whether they have any questions for "
                                "you. Answer briefly and realistically using the facts about the organisation, and do not "
                                "make up specific facts.\n") if asks else "",
        "close_n": 5 if asks else 4,
    }
    return _fill((PROMPTS_DIR / "script_stations.txt").read_text(encoding="utf-8").rstrip("\n"), values)


def build_system_prompt(pack: dict, history: list[dict] | None = None, brief: dict | None = None) -> str:
    """The interviewer's system prompt. `brief` is the session's brief; None is the default brief, which
    renders today's prompt exactly (raw JD / CV / notes and the standard conversation)."""
    from .brief import legacy_context, render_context

    opts = pack.get("options") or {}
    company = pack.get("company") or (brief or {}).get("organisation") or "the company"
    role = pack.get("role") or (brief or {}).get("role") or "the role"
    if brief is None:
        context = legacy_context(materials.legacy_slots(pack), "Company notes", "(none)")
    else:
        context = render_context(brief)
    if brief is not None and brief["format"]["kind"] == "stations":
        script = stations_script(opts, brief)
    else:
        script = conversation_script(opts, brief, company)
    values = {
        "interviewer_name": opts.get("interviewer_name") or "Alex",
        "style": opts.get("style") or "neutral",
        "company": company,
        "role": role,
        "context": context,
        "history": history_block(history),
        "script": script,
    }
    return _fill((PROMPTS_DIR / "interviewer.txt").read_text(encoding="utf-8"), values)


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
