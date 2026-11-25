"""SQLite helpers. The database lives in data/interview.db (git-ignored)."""

from __future__ import annotations

import json
import shutil
import statistics
import sqlite3
import time
import uuid
from pathlib import Path

from .categories import resolve_category

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "interview.db"
ANSWERS_DIR = DATA_DIR / "answers"  # <session_id>/<turn_idx>.wav, one per spoken answer

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
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id),
    question_key TEXT NOT NULL,
    question TEXT NOT NULL,
    category TEXT,
    answer_text TEXT NOT NULL,
    seconds REAL,               -- first word to end of answer
    audio_path TEXT,            -- data/answers/drill/<id>.wav
    result_json TEXT,           -- scores, average, tips, improved, better_answer, delivery
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS prep (
    pack_id TEXT PRIMARY KEY REFERENCES packs(id),
    source_hash TEXT,           -- SHA-1 of JD, CV and company notes when the sheet was written
    prep_json TEXT,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS attempts_by_question ON attempts (pack_id, question_key, created_at);
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
    "turns": {
        "t_listen_ms": "INTEGER",  # when the mic opened for this answer
        "face_json": "TEXT",       # per-answer face stats from the browser (numbers only)
        "words_json": "TEXT",      # word offsets in the answer WAV, filled in by the report step
        "segments_json": "TEXT",   # session-clock start/end of each kept speech segment (maps WAV offsets to the recording)
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


def next_turn_idx(session_id: str) -> int:
    """Index the next added turn will get (the current turn count)."""
    with connect() as conn:
        (idx,) = conn.execute("SELECT COUNT(*) FROM turns WHERE session_id = ?", (session_id,)).fetchone()
    return idx


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


def set_turn_segments(session_id: str, idx: int, segments: list | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE turns SET segments_json = ? WHERE session_id = ? AND idx = ?",
            (json.dumps(segments) if segments else None, session_id, idx),
        )


def set_turn_words(session_id: str, idx: int, words: list | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE turns SET words_json = ? WHERE session_id = ? AND idx = ?",
            (json.dumps(words) if words is not None else None, session_id, idx),
        )


def set_turn_face(session_id: str, idx: int, face: dict | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE turns SET face_json = ? WHERE session_id = ? AND idx = ?",
            (json.dumps(face) if face else None, session_id, idx),
        )


def set_turn_times(session_id: str, timeline: list[dict]) -> None:
    """timeline: [{turn_idx, t_start_ms, t_end_ms, t_listen_ms?}], times relative to the recording start."""
    with connect() as conn:
        conn.executemany(
            "UPDATE turns SET t_start_ms = ?, t_end_ms = ?, t_listen_ms = ? WHERE session_id = ? AND idx = ?",
            [(t.get("t_start_ms"), t.get("t_end_ms"), t.get("t_listen_ms"), session_id, t["turn_idx"]) for t in timeline],
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
    for a in (d["report"] or {}).get("answers") or []:  # older reports have no category
        a["category"] = resolve_category(a.get("category"), a.get("question", ""))
        a.setdefault("competency", "")
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
        d["face"] = json.loads(d.pop("face_json") or "null")
        d["words"] = json.loads(d.pop("words_json") or "null")
        d["segments"] = json.loads(d.pop("segments_json") or "null")
        out.append(d)
    return out


# ----------------------------------------------------- packs: edit/delete --- #

def update_pack(pack_id: str, data: dict) -> dict | None:
    with connect() as conn:
        conn.execute(
            "UPDATE packs SET title = ?, role = ?, company = ?, jd = ?, profile = ?, company_notes = ?, "
            "options_json = ? WHERE id = ?",
            (
                data["title"], data.get("role"), data.get("company"), data.get("jd"), data.get("profile"),
                data.get("company_notes"), json.dumps(data.get("options") or {}), pack_id,
            ),
        )
    return get_pack(pack_id)


def delete_session(session_id: str) -> str | None:
    """Delete a session with its turns and report. Returns its recording path."""
    with connect() as conn:
        row = conn.execute("SELECT recording_path FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM reports WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    shutil.rmtree(ANSWERS_DIR / session_id, ignore_errors=True)
    return row["recording_path"]


def delete_pack(pack_id: str) -> list[str]:
    """Delete a pack and all its sessions. Returns the recording paths to remove."""
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM sessions WHERE pack_id = ?", (pack_id,))]
    paths = [p for p in (delete_session(i) for i in ids) if p]
    with connect() as conn:
        paths += [r["audio_path"] for r in conn.execute(
            "SELECT audio_path FROM attempts WHERE pack_id = ? AND audio_path IS NOT NULL", (pack_id,))]
        conn.execute("DELETE FROM attempts WHERE pack_id = ?", (pack_id,))
        conn.execute("DELETE FROM prep WHERE pack_id = ?", (pack_id,))
        conn.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
    return paths


# ------------------------------------------------------------------ prep --- #

def get_prep(pack_id: str) -> dict | None:
    """The pack's prep sheet: {sheet, source_hash, created_at}, or None."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM prep WHERE pack_id = ?", (pack_id,)).fetchone()
    if not row or not row["prep_json"]:
        return None
    return {"sheet": json.loads(row["prep_json"]), "source_hash": row["source_hash"],
            "created_at": row["created_at"]}


def save_prep(pack_id: str, source_hash: str, sheet: dict) -> dict:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO prep (pack_id, source_hash, prep_json, created_at) VALUES (?, ?, ?, ?)",
            (pack_id, source_hash, json.dumps(sheet), _now_ms()),
        )
    return get_prep(pack_id)


# -------------------------------------------------------------- attempts --- #

DRILL_DIR = ANSWERS_DIR / "drill"


def _attempt_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    return d


def new_attempt_id() -> str:
    return uuid.uuid4().hex[:12]


def add_attempt(attempt_id: str, pack_id: str, key: str, question: str, category: str | None,
                answer_text: str, seconds: float | None, audio_path: str | None, result: dict) -> dict:
    with connect() as conn:
        conn.execute(
            "INSERT INTO attempts (id, pack_id, question_key, question, category, answer_text, seconds,"
            " audio_path, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt_id, pack_id, key, question, category, answer_text, seconds, audio_path,
             json.dumps(result), _now_ms()),
        )
        row = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    return _attempt_row(row)


def list_attempts(pack_id: str, key: str | None = None) -> list[dict]:
    """A pack's attempts, oldest first, optionally for one question key."""
    sql, args = "SELECT * FROM attempts WHERE pack_id = ?", [pack_id]
    if key:
        sql += " AND question_key = ?"
        args.append(key)
    with connect() as conn:
        rows = conn.execute(sql + " ORDER BY created_at, rowid", args).fetchall()
    return [_attempt_row(r) for r in rows]


def list_attempts_all() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM attempts ORDER BY created_at, rowid").fetchall()
    return [_attempt_row(r) for r in rows]


def update_attempt_result(attempt_id: str, result: dict) -> None:
    with connect() as conn:
        conn.execute("UPDATE attempts SET result_json = ? WHERE id = ?", (json.dumps(result), attempt_id))


def update_report_content(session_id: str, report: dict, report_md: str) -> None:
    """Rewrite a stored report's JSON and Markdown without touching its status or timestamp."""
    with connect() as conn:
        conn.execute("UPDATE reports SET report_json = ?, report_md = ? WHERE session_id = ?",
                     (json.dumps(report), report_md, session_id))


VOICE_BASELINE_MIN = 10


def voice_baseline(limit: int = 40, exclude_session: str | None = None, exclude_attempt: str | None = None) -> dict | None:
    """Median of each voice number over your newest ``limit`` answers that have voice stats.

    Draws on report answers and drill attempts, leaving out the session (or attempt) being scored.
    None below 10 answers. Medians skip missing values.
    """
    items: list[tuple[int, dict]] = []
    with connect() as conn:
        reports = conn.execute(
            "SELECT session_id, report_json, COALESCE(created_at, 0) AS ts FROM reports "
            "WHERE status = 'ready' AND report_json IS NOT NULL ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        attempts = conn.execute(
            "SELECT id, result_json, created_at AS ts FROM attempts WHERE result_json IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    for r in reports:
        if r["session_id"] == exclude_session:
            continue
        for a in (json.loads(r["report_json"]).get("answers") or []):
            v = (a.get("delivery") or {}).get("voice")
            if v:
                items.append((r["ts"], v))
    for r in attempts:
        if r["id"] == exclude_attempt:
            continue
        v = (json.loads(r["result_json"]).get("delivery") or {}).get("voice")
        if v:
            items.append((r["ts"], v))
    items.sort(key=lambda it: it[0], reverse=True)
    voices = [v for _, v in items[:limit]]
    if len(voices) < VOICE_BASELINE_MIN:
        return None
    out = {}
    for k in ("pitch_range_st", "loudness_range_db", "trail_off_pct"):
        vals = [v[k] for v in voices if v.get(k) is not None]
        out[k] = round(statistics.median(vals), 2) if vals else None
    return out


def face_baseline(limit: int = 40, exclude_session: str | None = None) -> dict | None:
    """Your usual expressiveness: the median over your newest ``limit`` report answers that have it.

    Eye contact has an absolute meaning, so only ``expressiveness`` gets a baseline. None below 10 answers.
    """
    items: list[tuple[int, float]] = []
    with connect() as conn:
        reports = conn.execute(
            "SELECT session_id, report_json, COALESCE(created_at, 0) AS ts FROM reports "
            "WHERE status = 'ready' AND report_json IS NOT NULL ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    for r in reports:
        if r["session_id"] == exclude_session:
            continue
        for a in (json.loads(r["report_json"]).get("answers") or []):
            v = ((a.get("delivery") or {}).get("face") or {}).get("expressiveness")
            if v is not None:
                items.append((r["ts"], v))
    items.sort(key=lambda it: it[0], reverse=True)
    vals = [v for _, v in items[:limit]]
    if len(vals) < VOICE_BASELINE_MIN:
        return None
    return {"expressiveness": round(statistics.median(vals), 2)}


# --------------------------------------------------------------- history --- #

CRITERIA = ("relevance", "structure", "specificity", "evidence")

# A session with fewer scored answers than this is "partial": shown in History but left out of trends.
MIN_SCORED_ANSWERS = 3


def is_partial(scored_answers: int | None) -> bool:
    """True when a report scored too few answers to be comparable. Unscored sessions are not partial."""
    return scored_answers is not None and scored_answers < MIN_SCORED_ANSWERS


def category_averages(answers: list[dict]) -> dict[str, dict]:
    """Per category: {average, answers}. Older reports without a category fall back on the question text."""
    groups: dict[str, list[float]] = {}
    for a in answers:
        avg = a.get("average")
        if avg is None:
            avg = sum(a["scores"].values()) / len(a["scores"])
        groups.setdefault(resolve_category(a.get("category"), a.get("question", "")), []).append(avg)
    return {c: {"average": round(sum(v) / len(v), 2), "answers": len(v)} for c, v in groups.items()}


def _session_summary(row: sqlite3.Row) -> dict:
    d = dict(row)
    report = json.loads(d.pop("report_json")) if d.get("report_json") else None
    d["criteria"] = None
    d["filler_count"] = None
    d["avg_answer_seconds"] = None
    d["answers"] = None
    d["partial"] = False
    d["by_category"] = {}
    if report and report.get("answers"):
        answers = report["answers"]
        d["criteria"] = {
            c: round(sum(a["scores"][c] for a in answers) / len(answers), 2) for c in CRITERIA
        }
        d["filler_count"] = (report.get("filler_words") or {}).get("count")
        d["avg_answer_seconds"] = report.get("avg_answer_seconds")
        d["answers"] = len(answers)
        d["partial"] = is_partial(len(answers))
        d["by_category"] = category_averages(answers)
    return d


def pack_history(pack_id: str) -> list[dict]:
    """A pack's finished sessions, oldest first, with score breakdowns."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT s.id, s.pack_id, s.started_at, s.ended_at, s.overall_score, "
            "s.recording_path IS NOT NULL AS has_recording, r.status AS report_status, r.report_json "
            "FROM sessions s LEFT JOIN reports r ON r.session_id = s.id "
            "WHERE s.pack_id = ? AND s.ended_at IS NOT NULL ORDER BY s.started_at",
            (pack_id,),
        ).fetchall()
    return [_session_summary(r) for r in rows]


def history() -> list[dict]:
    """Every pack (most recently used first) with its session history."""
    out = []
    for pack in list_packs():
        sessions = pack_history(pack["id"])
        last = max([s["started_at"] for s in sessions], default=pack["created_at"])
        out.append({"pack": pack, "sessions": sessions, "last_used": last})
    out.sort(key=lambda x: -x["last_used"])
    return out


def pack_report_history(pack_id: str, limit: int = 3, before: int | None = None) -> list[dict]:
    """The latest scored, non-partial sessions of a pack, newest first.

    Each item is {started_at, answers: [{question, category, average}], top_fixes}.
    `before` (a started_at in ms) keeps only sessions that started earlier, so a
    regenerated report only sees the sessions that preceded it.
    """
    sql = (
        "SELECT s.started_at, r.report_json FROM sessions s JOIN reports r ON r.session_id = s.id "
        "WHERE s.pack_id = ? AND r.status = 'ready' AND r.report_json IS NOT NULL "
    )
    args: list = [pack_id]
    if before is not None:
        sql += "AND s.started_at < ? "
        args.append(before)
    sql += "ORDER BY s.started_at DESC"
    out: list[dict] = []
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    for row in rows:
        report = json.loads(row["report_json"])
        answers = report.get("answers") or []
        if not answers or is_partial(len(answers)):
            continue
        out.append({
            "started_at": row["started_at"],
            "answers": [
                {
                    "question": a.get("question", ""),
                    "category": resolve_category(a.get("category"), a.get("question", "")),
                    "average": a.get("average") if a.get("average") is not None
                    else round(sum(a["scores"].values()) / len(a["scores"]), 1),
                }
                for a in answers
            ],
            "top_fixes": [str(f) for f in report.get("top_fixes") or []],
        })
        if len(out) >= limit:
            break
    return out
