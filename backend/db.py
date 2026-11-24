"""SQLite helpers. The database lives in data/interview.db (git-ignored)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "interview.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    role TEXT,
    company TEXT,
    jd TEXT,
    profile TEXT,
    company_notes TEXT,
    options_json TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id),
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    recording_path TEXT,
    overall_score REAL
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    idx INTEGER NOT NULL,
    speaker TEXT NOT NULL,          -- 'interviewer' | 'candidate'
    text TEXT NOT NULL,
    expressions_json TEXT,
    t_start_ms INTEGER,
    t_end_ms INTEGER
);
CREATE TABLE IF NOT EXISTS reports (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    report_json TEXT,
    report_md TEXT
);
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after Milestone 1 (ALTER TABLE for existing databases).
_EXTRA_COLUMNS = {
    "reports": {
        "status": "TEXT",          # 'pending' | 'ready' | 'error'
        "error": "TEXT",
        "created_at": "INTEGER",
    },
}


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, cols in _EXTRA_COLUMNS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        # A report still 'pending' at startup was interrupted by a restart.
        conn.execute(
            "UPDATE reports SET status = 'error', error = 'Interrupted by a server restart' "
            "WHERE status = 'pending'"
        )


# ---------------------------------------------------------------- packs ---- #

def _pack_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["options"] = json.loads(d.pop("options_json") or "{}")
    return d


def create_pack(data: dict) -> dict:
    pack_id = uuid.uuid4().hex[:12]
    with connect() as conn:
        conn.execute(
            "INSERT INTO packs (id, title, role, company, jd, profile, company_notes, options_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pack_id, data["title"], data.get("role"), data.get("company"), data.get("jd"),
                data.get("profile"), data.get("company_notes"),
                json.dumps(data.get("options") or {}), _now_ms(),
            ),
        )
    return get_pack(pack_id)


def list_packs() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM packs ORDER BY created_at DESC").fetchall()
    return [_pack_row(r) for r in rows]


def get_pack(pack_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM packs WHERE id = ?", (pack_id,)).fetchone()
    return _pack_row(row) if row else None


# ------------------------------------------------------------- sessions ---- #

def create_session(pack_id: str) -> str:
    session_id = uuid.uuid4().hex[:12]
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, pack_id, started_at) VALUES (?, ?, ?)",
            (session_id, pack_id, _now_ms()),
        )
    return session_id


def end_session(session_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (_now_ms(), session_id),
        )


def get_session(session_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def add_turn(session_id: str, speaker: str, text: str, expressions: list | None = None) -> int:
    """Append a turn and return its index within the session."""
    with connect() as conn:
        (idx,) = conn.execute(
            "SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)
        ).fetchone()
        conn.execute(
            "INSERT INTO turns (session_id, idx, speaker, text, expressions_json) VALUES (?, ?, ?, ?, ?)",
            (session_id, idx, speaker, text, json.dumps(expressions) if expressions is not None else None),
        )
    return idx


def set_turn_times(session_id: str, timeline: list[dict]) -> None:
    """timeline: [{turn_idx, t_start_ms, t_end_ms}], times relative to the recording start."""
    with connect() as conn:
        conn.executemany(
            "UPDATE turns SET t_start_ms = ?, t_end_ms = ? WHERE session_id = ? AND idx = ?",
            [(t.get("t_start_ms"), t.get("t_end_ms"), session_id, t["turn_idx"]) for t in timeline],
        )


def set_recording(session_id: str, path: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE sessions SET recording_path = ? WHERE id = ?", (path, session_id))


def set_overall_score(session_id: str, score: float | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE sessions SET overall_score = ? WHERE id = ?", (score, session_id))


def list_sessions(limit: int = 20, pack_id: str | None = None) -> list[dict]:
    sql = (
        "SELECT s.*, p.title AS pack_title, p.role, p.company, r.status AS report_status "
        "FROM sessions s JOIN packs p ON p.id = s.pack_id "
        "LEFT JOIN reports r ON r.session_id = s.id "
    )
    args: list = []
    if pack_id:
        sql += "WHERE s.pack_id = ? "
        args.append(pack_id)
    sql += "ORDER BY s.started_at DESC LIMIT ?"
    args.append(limit)
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


# -------------------------------------------------------------- reports ---- #

def set_report_pending(session_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO reports (session_id, status, error, created_at) VALUES (?, 'pending', NULL, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET status = 'pending', error = NULL",
            (session_id, _now_ms()),
        )


def save_report(session_id: str, report: dict, report_md: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE reports SET report_json = ?, report_md = ?, status = 'ready', error = NULL, created_at = ? "
            "WHERE session_id = ?",
            (json.dumps(report), report_md, _now_ms(), session_id),
        )


def set_report_error(session_id: str, error: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE reports SET status = 'error', error = ? WHERE session_id = ?", (error, session_id)
        )


def get_report(session_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["report"] = json.loads(d.pop("report_json")) if d.get("report_json") else None
    return d


def list_turns(session_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY idx", (session_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["expressions"] = json.loads(d.pop("expressions_json") or "[]")
        out.append(d)
    return out
