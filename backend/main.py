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
import re
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import db, feedback, gpu, stt, tts
from .brain import (
    OPENING_CUE,
    time_note,
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
    return problems


@dataclass
class LiveSession:
    brain: InterviewBrain
    voice: str
    stt_prompt: str
    options: dict
    started_at_ms: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_active: float = field(default_factory=time.monotonic)


# Interviews with no activity for this long are ended and scored automatically
# (tab closed, laptop slept...). Set IDLE_TIMEOUT_MIN=0 to disable.
IDLE_TIMEOUT_S = float(os.environ.get("IDLE_TIMEOUT_MIN") or 30) * 60

# Active interviews (lost on server restart).
LIVE: dict[str, LiveSession] = {}
# Feedback reports being written: session_id -> task.
REPORT_TASKS: dict[str, asyncio.Task] = {}


def recordings_dir() -> Path:
    return db.DATA_DIR / "recordings"


def start_report(session_id: str) -> None:
    task = REPORT_TASKS.get(session_id)
    if task and not task.done():
        return
    db.set_report_pending(session_id)
    task = asyncio.create_task(feedback.generate(session_id))
    REPORT_TASKS[session_id] = task
    task.add_done_callback(lambda _: REPORT_TASKS.pop(session_id, None))


async def load_models() -> None:
    """Load Whisper then Kokoro on the MLX thread, without blocking startup."""
    await gpu.run(stt.load)
    await gpu.run(tts.load)


async def finish_session(session_id: str, timeline: list[dict] | None = None) -> None:
    """Close the Claude client, store turn timings, mark the session ended and start its report."""
    live = LIVE.pop(session_id, None)
    if live:
        await live.brain.close()
    if timeline:
        db.set_turn_times(session_id, timeline)
    db.end_session(session_id)
    report = db.get_report(session_id)
    if not report or report["status"] == "error":
        start_report(session_id)


async def reap_idle_sessions() -> None:
    """Finish interviews nobody has touched for IDLE_TIMEOUT_S so they are not lost."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for sid, live in list(LIVE.items()):
            if not live.lock.locked() and now - live.last_active > IDLE_TIMEOUT_S:
                log.info("Ending idle session %s", sid)
                try:
                    await finish_session(sid)
                except Exception:
                    log.exception("Could not end idle session %s", sid)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Refusing to start: ANTHROPIC_API_KEY is set and would bill the API instead of "
            "your Claude subscription. Unset it and sign in with `claude login` instead."
        )
    db.init()
    loader = asyncio.create_task(load_models())
    reaper = asyncio.create_task(reap_idle_sessions()) if IDLE_TIMEOUT_S > 0 else None
    yield
    loader.cancel()
    if reaper:
        reaper.cancel()
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


class TurnTiming(BaseModel):
    turn_idx: int
    t_start_ms: int | None = None
    t_end_ms: int | None = None


class EndIn(BaseModel):
    # When each turn started/ended, in ms from the start of the recording.
    timeline: list[TurnTiming] = []


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
    turn_idx: int | None = None
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
        if full_text:
            turn_idx = db.add_turn(session_id, "interviewer", full_text, expressions)
        yield _line({
            "type": "done",
            "turn_idx": turn_idx,
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
        if full_text and turn_idx is None:  # stream cut short: keep what was said
            db.add_turn(session_id, "interviewer", full_text, expressions)
        live.last_active = time.monotonic()
        if live.lock.locked():
            live.lock.release()


# ---------------------------------------------------------------- routes --- #

@app.get("/health")
async def health():
    problems = auth_problems()
    body = {
        "ok": not problems,
        "claude_auth": ("subscription token" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else "Claude Code login") if not problems else "problem",
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


MAX_PDF_BYTES = 10 * 1024 * 1024


def _pdf_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("The PDF is password protected")
    pages = [re.sub(r"[ \t]+\n", "\n", p.extract_text() or "").strip() for p in reader.pages]
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(p for p in pages if p)).strip()


@app.post("/extract-text")
async def extract_text(file: UploadFile):
    """Text of an uploaded PDF, to fill the job description / CV fields."""
    data = await file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "The PDF is larger than 10 MB")
    try:
        text = await asyncio.to_thread(_pdf_text, data)
    except Exception as exc:
        raise HTTPException(422, f"Could not read the PDF: {exc}")
    if not text:
        raise HTTPException(422, "No text found in the PDF (is it a scan?). Paste the text instead.")
    return {"text": text, "chars": len(text)}


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


@app.put("/packs/{pack_id}")
async def update_pack(pack_id: str, pack: PackIn):
    if not db.get_pack(pack_id):
        raise HTTPException(404, "Pack not found")
    return db.update_pack(pack_id, pack.model_dump())


def _remove_files(paths: list[str]) -> None:
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", p, exc)


@app.delete("/packs/{pack_id}")
async def delete_pack(pack_id: str):
    """Delete a pack with all its sessions, reports and recordings."""
    if not db.get_pack(pack_id):
        raise HTTPException(404, "Pack not found")
    if any(s["pack_id"] == pack_id for s in db.list_sessions(limit=1000) if s["id"] in LIVE):
        raise HTTPException(409, "An interview with this pack is still running")
    _remove_files(db.delete_pack(pack_id))
    return {"deleted": pack_id}


@app.get("/packs/{pack_id}/history")
async def pack_history(pack_id: str):
    if not db.get_pack(pack_id):
        raise HTTPException(404, "Pack not found")
    return db.pack_history(pack_id)


@app.get("/history")
async def history():
    """All packs with their finished sessions and score breakdowns."""
    return db.history()


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
        options=opts,
        started_at_ms=int(time.time() * 1000),
        voice=opts.get("voice") if opts.get("voice") in tts.VOICES else tts.DEFAULT_VOICE,
        stt_prompt=stt.keyword_prompt(pack.get("role", ""), pack.get("company", ""), pack.get("jd", "")),
    )
    LIVE[session_id] = live
    await live.lock.acquire()  # released when the stream finishes
    return StreamingResponse(
        speak(session_id, live, brain.stream(OPENING_CUE), [{"type": "session", "session_id": session_id}], t0),
        media_type="application/x-ndjson",
    )


def _save_answer_audio(session_id: str, turn_idx: int, data: bytes) -> None:
    try:
        folder = db.ANSWERS_DIR / session_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{turn_idx}.wav").write_bytes(data)
    except OSError as exc:
        log.warning("Could not save answer audio: %s", exc)


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
        audio_bytes = None
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("audio")
            if upload is None or isinstance(upload, str):
                raise HTTPException(422, "Missing `audio` file")
            if not stt.is_ready():
                raise HTTPException(503, f"Speech recognition is not ready ({stt.state['status']})")
            data = await upload.read()
            audio_bytes = data
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

    turn_idx = db.add_turn(session_id, "candidate", answer)
    if audio_bytes:
        asyncio.create_task(asyncio.to_thread(_save_answer_audio, session_id, turn_idx, audio_bytes))
    to_claude = time_note(live.options, live.started_at_ms, int(time.time() * 1000)) + answer
    return StreamingResponse(
        speak(session_id, live, live.brain.stream(to_claude),
              [{"type": "transcript", "text": answer, "stt_ms": stt_ms, "turn_idx": turn_idx}], t0),
        media_type="application/x-ndjson",
    )


@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str, body: EndIn | None = None):
    """Close the Claude client, store turn timings and start the feedback report."""
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    await finish_session(session_id, [t.model_dump() for t in body.timeline] if body else None)
    return {"session_id": session_id, "ended": True, "report_status": "pending"}


@app.get("/sessions")
async def list_sessions(limit: int = 20, pack_id: str | None = None):
    return db.list_sessions(limit=max(1, min(limit, 200)), pack_id=pack_id)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    report = db.get_report(session_id)
    return {
        **session,
        "has_recording": bool(session.get("recording_path")) and Path(session["recording_path"]).exists(),
        "pack": db.get_pack(session["pack_id"]),
        "turns": db.list_turns(session_id),
        "report_status": report["status"] if report else None,
    }


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session with its transcript, report and recording."""
    if session_id in LIVE:
        raise HTTPException(409, "End the interview first")
    if session_id in REPORT_TASKS:
        raise HTTPException(409, "The report is still being written")
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    path = db.delete_session(session_id)
    _remove_files([path] if path else [])
    return {"deleted": session_id}


@app.get("/sessions/{session_id}/turns")
async def session_turns(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    return db.list_turns(session_id)


@app.post("/sessions/{session_id}/recording")
async def upload_recording(session_id: str, recording: UploadFile):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    folder = recordings_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.webm"
    tmp = path.with_suffix(".part")
    with tmp.open("wb") as f:
        await asyncio.to_thread(shutil.copyfileobj, recording.file, f, 1024 * 1024)
    tmp.replace(path)
    db.set_recording(session_id, str(path))
    return {"session_id": session_id, "bytes": path.stat().st_size}


def _download_name(session: dict, ext: str) -> str:
    from datetime import datetime

    pack = db.get_pack(session["pack_id"]) or {}
    slug = re.sub(r"[^a-z0-9]+", "-", (pack.get("title") or "interview").lower()).strip("-")[:40]
    when = datetime.fromtimestamp(session["started_at"] / 1000).strftime("%Y-%m-%d-%H%M")
    return f"{slug or 'interview'}-{when}.{ext}"


@app.get("/sessions/{session_id}/recording")
async def get_recording(session_id: str, download: bool = False):
    session = db.get_session(session_id)
    if not session or not session.get("recording_path") or not Path(session["recording_path"]).exists():
        raise HTTPException(404, "No recording for this session")
    return FileResponse(
        session["recording_path"],
        media_type="video/webm",
        filename=_download_name(session, "webm") if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/sessions/{session_id}/report")
async def get_report(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    report = db.get_report(session_id)
    if not report:
        return {"status": "none", "report": None, "report_md": None, "error": None}
    return {k: report.get(k) for k in ("status", "report", "report_md", "error")}


@app.post("/sessions/{session_id}/report")
async def regenerate_report(session_id: str):
    """Write the report again (one more Claude request)."""
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    if session_id in LIVE:
        raise HTTPException(409, "End the interview first")
    start_report(session_id)
    return {"status": "pending"}


@app.get("/sessions/{session_id}/report.md")
async def get_report_md(session_id: str):
    session = db.get_session(session_id)
    report = db.get_report(session_id) if session else None
    if not report or not report.get("report_md"):
        raise HTTPException(404, "No report for this session yet")
    return PlainTextResponse(
        report["report_md"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_download_name(session, "md")}"'},
    )
