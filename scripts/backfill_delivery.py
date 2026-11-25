"""Recompute delivery stats for stored reports and drill attempts from saved WAVs. Never calls Claude.

    python -m scripts.backfill_delivery

Every report's per-answer ``delivery`` is rebuilt from its transcript and ``data/answers/<session>/``;
every drill attempt with audio gets its voice fields. Scores and text are left as they are. Runs in two
passes so the voice baseline exists before any flags are set (PLAN-energy.md, 1c).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, delivery, feedback  # noqa: E402


def _reports() -> list[tuple[dict, dict]]:
    out = []
    for s in db.list_sessions(limit=100000):
        rec = db.get_report(s["id"])
        if rec and rec.get("status") == "ready" and rec.get("report"):
            out.append((s, rec["report"]))
    return out


def main() -> None:
    db.init()
    reports = _reports()
    attempts = [a for a in db.list_attempts_all() if a.get("audio_path") and a.get("result")]
    # Pass 1: stats and voice numbers, no baseline yet.
    for s, report in reports:
        turns = db.list_turns(s["id"])
        delivery.answer_delivery(report["answers"], turns, db.ANSWERS_DIR / s["id"])
        pack = db.get_pack(s["pack_id"]) or {}
        db.update_report_content(s["id"], report, feedback.to_markdown(report, pack, db.get_session(s["id"]) or s, turns))
    for a in attempts:
        res = a["result"]
        voice = delivery.voice_from_wavs([a["audio_path"]])
        res["delivery"] = {**(res.get("delivery") or {}), **delivery.voice_fields(voice, None)}
        db.update_attempt_result(a["id"], res)
    # Pass 2: flags against the baseline, leaving each answer's own session or attempt out of it.
    flagged = 0
    for s, report in reports:
        base = db.voice_baseline(exclude_session=s["id"])
        for ans in report["answers"]:
            d = ans.get("delivery")
            if d:
                d.update(delivery.voice_fields(d.get("voice"), base))
                flagged += bool(d["voice_flags"])
        turns = db.list_turns(s["id"])
        pack = db.get_pack(s["pack_id"]) or {}
        db.update_report_content(s["id"], report, feedback.to_markdown(report, pack, db.get_session(s["id"]) or s, turns))
    for a in attempts:
        res = a["result"]
        d = res["delivery"]
        d.update(delivery.voice_fields(d.get("voice"), db.voice_baseline(exclude_attempt=a["id"])))
        flagged += bool(d["voice_flags"])
        db.update_attempt_result(a["id"], res)
    print(f"{len(reports)} reports and {len(attempts)} drill attempts with audio updated; {flagged} answers flagged")
    if db.voice_baseline() is None:
        print(f"Fewer than {db.VOICE_BASELINE_MIN} answers have voice stats, so fixed thresholds were used.")


if __name__ == "__main__":
    main()
