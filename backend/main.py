"""FastAPI app: interview packs, sessions and voice turns.

Run from the repo root:  uvicorn backend.main:app --port 8000

/sessions and /sessions/{id}/turn stream their reply as NDJSON (one JSON object
per line) so the browser can start playing the first sentence while Claude is
still writing the rest:

  {"type": "session", "session_id"}                      (POST /sessions only)
  {"type": "transcript", "text", "stt_ms"}               (POST /turn only)
  {"type": "sentence", "index", "text", "expressions", "audio_wav_base64",
   "duration_ms", "word_timings", "tts_error"}           (one per sentence)
  {"type": "done", "reply_text", "expressions", "is_final", "timings"}
  {"type": "error", "message"}                           (instead of done)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db, gpu, stt, tts
from .brain import (
    OPENING_CUE,
    BrainError,
    InterviewBrain,
    SentenceSplitter,
    build_system_prompt,
    parse_tags,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("interview-coach")
ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines). Real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")


def auth_problems() -> list[str]:
    problems = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        problems.append(
            "ANTHROPIC_API_KEY is set: it would bill the API instead of your subscription. "
            "Unset it (shell and .env) and restart."
        )
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        problems.append("CLAUDE_CODE_OAUTH_TOKEN is missing: run `claude setup-token` and put it in .env.")
    return problems


@dataclass
class LiveSession:
    brain: InterviewBrain
    voice: str
    stt_prompt: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Active interviews (lost on server restart).
LIVE: dict[str, LiveSession] = {}


async def load_models() -> None:
    """Load Whisper then Kokoro on the MLX thread, without blocking startup."""
    await gpu.run(stt.load)
    await gpu.run(tts.load)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Refusing to start: ANTHROPIC_API_KEY is set and would bill the API instead of "
            "your Claude subscription. Unset it and use CLAUDE_CODE_OAUTH_TOKEN."
        )
    db.init()
    loader = asyncio.create_task(load_models())
    yield
    loader.cancel()
    for live in list(LIVE.values()):
        await live.brain.close()
    LIVE.clear()


app = FastAPI(title="Interview Coach", lifespan=lifespan)


# ---------------------------------------------------------------- models --- #

class PackOptions(BaseModel):
    interview_type: Literal["behavioural", "technical", "mixed", "case"] = "mixed"
    num_questions: int = Field(5, ge=1, le=20)
    minutes: int | None = Field(None, ge=5, le=120)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    style: Literal["friendly", "neutral", "tough"] = "neutral"
    interviewer_name: str = "Alex"
    voice: str = tts.DEFAULT_VOICE


class PackIn(BaseModel):
    title: str = Field(..., min_length=1)
    role: str = ""
    company: str = ""
    jd: str = Field(..., min_length=1)
    profile: str = ""
    company_notes: str = ""
    options: PackOptions = PackOptions()


class SessionIn(BaseModel):
    pack_id: str


# ------------------------------------------------------------- streaming --- #

def _line(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


async def speak(
    session_id: str,
    live: LiveSession,
    raw: AsyncIterator[str],
    prelude: list[dict],
    t0: float,
) -> AsyncIterator[bytes]:
    """Turn Claude's streamed text into voiced sentences, in order.

    A producer task reads Claude's deltas, cuts sentences and queues each one's
    TTS job on the MLX thread right away, so sentence 1 is being voiced while
    Claude is still writing sentence 2.
    """
    queue: asyncio.Queue = asyncio.Queue()
    voice_on = tts.is_ready()

    def enqueue(chunk: str) -> None:
        parsed = parse_tags(chunk)
        job = gpu.submit(tts.synthesize, parsed.text, live.voice) if (parsed.text and voice_on) else None
        queue.put_nowait((parsed, job))

    async def produce() -> None:
        splitter = SentenceSplitter()
        try:
            async for delta in raw:
                for chunk in splitter.feed(delta):
                    enqueue(chunk)
            for chunk in splitter.flush():
                enqueue(chunk)
            queue.put_nowait(None)
        except Exception as exc:
            queue.put_nowait(exc)

    producer = asyncio.create_task(produce())
    full_text, expressions, is_final, index = "", [], False, 0
    first_audio_ms = None
    try:
        for ev in prelude:
            yield _line(ev)
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                msg = str(item) if isinstance(item, BrainError) else f"{type(item).__name__}: {item}"
                yield _line({"type": "error", "message": msg})
                return
            parsed, job = item
            is_final = is_final or parsed.is_final
            if not parsed.text:
                continue
            audio, tts_error = None, None
            if job is not None:
                try:
                    audio = await asyncio.wrap_future(job)
                except Exception as exc:
                    tts_error = f"{type(exc).__name__}: {exc}"
                    log.warning("TTS failed for %r: %s", parsed.text, exc)
            offset = len(full_text) + (1 if full_text else 0)
            full_text = f"{full_text} {parsed.text}" if full_text else parsed.text
            expressions += [{"tag": e["tag"], "char_index": e["char_index"] + offset} for e in parsed.expressions]
            if index == 0:
                first_audio_ms = round((time.perf_counter() - t0) * 1000)
            yield _line({
                "type": "sentence",
                "index": index,
                "text": parsed.text,
                "expressions": parsed.expressions,
                "audio_wav_base64": audio["audio_wav_base64"] if audio else None,
                "duration_ms": audio["duration_ms"] if audio else 0,
                "word_timings": audio["word_timings"] if audio else [],
                "tts_error": tts_error,
            })
            index += 1
        yield _line({
            "type": "done",
            "reply_text": full_text,
            "expressions": expressions,
            "is_final": is_final,
            "timings": {
                "first_sentence_ms": first_audio_ms,
                "total_ms": round((time.perf_counter() - t0) * 1000),
            },
        })
    finally:
        if not producer.done():
            producer.cancel()
        if full_text:
            db.add_turn(session_id, "interviewer", full_text, expressions)
        if live.lock.locked():
            live.lock.release()


# ---------------------------------------------------------------- routes --- #

@app.get("/health")
async def health():
    problems = auth_problems()
    body = {
        "ok": not problems,
        "claude_auth": "subscription token" if not problems else "problem",
        "problems": problems,
        "whisper": {"model": stt.MODEL, **stt.state},
        "kokoro": {"model": tts.MODEL, **tts.state},
        "voice_ready": stt.is_ready() and tts.is_ready(),
        "active_sessions": len(LIVE),
    }
    return JSONResponse(body, status_code=200 if not problems else 503)


@app.get("/voices")
async def voices():
    return {"default": tts.DEFAULT_VOICE, "voices": tts.VOICES}


@app.post("/packs")
async def create_pack(pack: PackIn):
    return db.create_pack(pack.model_dump())


@app.get("/packs")
async def list_packs():
    return db.list_packs()


@app.get("/packs/{pack_id}")
async def get_pack(pack_id: str):
    pack = db.get_pack(pack_id)
    if not pack:
        raise HTTPException(404, "Pack not found")
    return pack


@app.post("/sessions")
async def start_session(body: SessionIn):
    t0 = time.perf_counter()
    problems = auth_problems()
    if problems:
        raise HTTPException(503, " ".join(problems))
    pack = db.get_pack(body.pack_id)
    if not pack:
        raise HTTPException(404, "Pack not found")

    brain = InterviewBrain(build_system_prompt(pack))
    try:
        await brain.start()
    except BrainError as exc:
        await brain.close()
        raise HTTPException(502, str(exc))

    session_id = db.create_session(pack["id"])
    opts = pack.get("options") or {}
    live = LiveSession(
        brain=brain,
        voice=opts.get("voice") if opts.get("voice") in tts.VOICES else tts.DEFAULT_VOICE,
        stt_prompt=stt.keyword_prompt(pack.get("role", ""), pack.get("company", ""), pack.get("jd", "")),
    )
    LIVE[session_id] = live
    await live.lock.acquire()  # released when the stream finishes
    return StreamingResponse(
        speak(session_id, live, brain.stream(OPENING_CUE), [{"type": "session", "session_id": session_id}], t0),
        media_type="application/x-ndjson",
    )


@app.post("/sessions/{session_id}/turn")
async def take_turn(session_id: str, request: Request):
    """Body: multipart with an `audio` WAV file, or JSON {"text": "..."}."""
    t0 = time.perf_counter()
    live = LIVE.get(session_id)
    if not live:
        raise HTTPException(404, "Session is not active (ended, or the server restarted)")
    if live.lock.locked():
        raise HTTPException(409, "The interviewer is still replying to the previous turn")
    await live.lock.acquire()
    try:
        stt_ms = None
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("audio")
            if upload is None or isinstance(upload, str):
                raise HTTPException(422, "Missing `audio` file")
            if not stt.is_ready():
                raise HTTPException(503, f"Speech recognition is not ready ({stt.state['status']})")
            data = await upload.read()
            try:
                answer = await gpu.run(stt.transcribe, data, live.stt_prompt)
            except Exception as exc:
                raise HTTPException(422, f"Could not read the audio: {exc}")
            stt_ms = round((time.perf_counter() - t0) * 1000)
            if not answer:
                raise HTTPException(422, "Didn't catch that. Please answer again.")
        else:
            body = await request.json()
            answer = str((body or {}).get("text") or "").strip()
            if not answer:
                raise HTTPException(422, "Empty answer")
    except BaseException:
        live.lock.release()
        raise

    db.add_turn(session_id, "candidate", answer)
    return StreamingResponse(
        speak(session_id, live, live.brain.stream(answer),
              [{"type": "transcript", "text": answer, "stt_ms": stt_ms}], t0),
        media_type="application/x-ndjson",
    )


@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    live = LIVE.pop(session_id, None)
    if live:
        await live.brain.close()
    db.end_session(session_id)
    # Feedback report generation arrives in Milestone 3.
    return {"session_id": session_id, "ended": True}


@app.get("/sessions/{session_id}/turns")
async def session_turns(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    return db.list_turns(session_id)
