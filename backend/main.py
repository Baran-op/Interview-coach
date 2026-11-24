"""FastAPI app: interview packs, sessions and turns.

Run from the repo root:  uvicorn backend.main:app --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db
from .brain import BrainError, InterviewBrain, build_system_prompt

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


# Active interviews: session_id -> InterviewBrain (lost on server restart).
BRAINS: dict[str, InterviewBrain] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "Refusing to start: ANTHROPIC_API_KEY is set and would bill the API instead of "
            "your Claude subscription. Unset it and use CLAUDE_CODE_OAUTH_TOKEN."
        )
    db.init()
    yield
    for brain in list(BRAINS.values()):
        await brain.close()
    BRAINS.clear()


app = FastAPI(title="Interview Coach", lifespan=lifespan)


# ---------------------------------------------------------------- models --- #

class PackOptions(BaseModel):
    interview_type: Literal["behavioural", "technical", "mixed", "case"] = "mixed"
    num_questions: int = Field(5, ge=1, le=20)
    minutes: int | None = Field(None, ge=5, le=120)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    style: Literal["friendly", "neutral", "tough"] = "neutral"
    interviewer_name: str = "Alex"


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


class TurnIn(BaseModel):
    text: str = Field(..., min_length=1)


class InterviewerReply(BaseModel):
    session_id: str
    transcript: str | None = None   # what the candidate said (echo for text mode)
    reply_text: str
    expressions: list[dict]
    is_final: bool


# ---------------------------------------------------------------- routes --- #

@app.get("/health")
async def health():
    problems = auth_problems()
    body = {
        "ok": not problems,
        "claude_auth": "subscription token" if not problems else "problem",
        "problems": problems,
        "whisper": "not loaded (milestone 2)",
        "kokoro": "not loaded (milestone 2)",
        "active_sessions": len(BRAINS),
    }
    return JSONResponse(body, status_code=200 if not problems else 503)


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


@app.post("/sessions", response_model=InterviewerReply)
async def start_session(body: SessionIn):
    problems = auth_problems()
    if problems:
        raise HTTPException(503, " ".join(problems))
    pack = db.get_pack(body.pack_id)
    if not pack:
        raise HTTPException(404, "Pack not found")

    brain = InterviewBrain(build_system_prompt(pack))
    try:
        await brain.start()
        reply = await brain.open()
    except BrainError as exc:
        await brain.close()
        raise HTTPException(502, str(exc))

    session_id = db.create_session(pack["id"])
    BRAINS[session_id] = brain
    db.add_turn(session_id, "interviewer", reply.text, reply.expressions)
    return InterviewerReply(
        session_id=session_id, reply_text=reply.text,
        expressions=reply.expressions, is_final=reply.is_final,
    )


@app.post("/sessions/{session_id}/turn", response_model=InterviewerReply)
async def take_turn(session_id: str, body: TurnIn):
    brain = BRAINS.get(session_id)
    if not brain:
        raise HTTPException(404, "Session is not active (ended, or the server restarted)")
    answer = body.text.strip()
    db.add_turn(session_id, "candidate", answer)
    try:
        reply = await brain.send(answer)
    except BrainError as exc:
        raise HTTPException(502, str(exc))
    db.add_turn(session_id, "interviewer", reply.text, reply.expressions)
    return InterviewerReply(
        session_id=session_id, transcript=answer, reply_text=reply.text,
        expressions=reply.expressions, is_final=reply.is_final,
    )


@app.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    brain = BRAINS.pop(session_id, None)
    if brain:
        await brain.close()
    db.end_session(session_id)
    # Feedback report generation arrives in Milestone 3.
    return {"session_id": session_id, "ended": True}


@app.get("/sessions/{session_id}/turns")
async def session_turns(session_id: str):
    if not db.get_session(session_id):
        raise HTTPException(404, "Session not found")
    return db.list_turns(session_id)
