"""Recompute delivery stats for stored reports and drill attempts from saved WAVs. Never calls Claude.

    python -m scripts.backfill_delivery

Every report's per-answer ``delivery`` is rebuilt from its transcript and ``data/answers/<session>/``;
every drill attempt with audio gets its voice fields. Spoken turns with a saved WAV but no word
offsets get them from Whisper (about 5 s per 80 s answer; skipped when mlx-whisper is missing), for the
quotes under face moments and flat stretches. Face stats (from each turn's stored `face_json`) are
combined per answer, with flags and moments, in the same passes. Flat voice stretches (``delivery.voice.sections``, PLAN-voice.md V6)
are filled from the WAVs and word offsets, never with advice, and stretches that already have advice are left untouched. Scores and text are left as they are. Runs in two
passes so the voice baseline exists before any flags are set (PLAN-energy.md, 1c).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import brief, db, delivery, feedback, stt, voice  # noqa: E402


def _reports() -> list[tuple[dict, dict]]:
    out = []
    for s in db.list_sessions(limit=100000):
        rec = db.get_report(s["id"])
        if rec and rec.get("status") == "ready" and rec.get("report"):
            out.append((s, rec["report"]))
    return out


def _fill_words(session_id: str, turns: list[dict]) -> None:
    for t in feedback.turns_needing_words(turns):
        path = db.ANSWERS_DIR / session_id / f"{t['idx']}.wav"
        if not path.exists():
            continue
        try:
            t["words"] = stt.words_from_wav(path)
            db.set_turn_words(session_id, t["idx"], t["words"])
        except Exception as exc:  # no mlx-whisper, no model
            print(f"  no word timestamps for {session_id} turn {t['idx']}: {exc}")
            return


def main() -> None:
    db.init()
    reports = _reports()
    attempts = [a for a in db.list_attempts_all() if a.get("audio_path") and a.get("result")]
    # Flat stretches that already carry advice are kept as they are (the advice refers to them).
    kept = {(s["id"], a.get("question_turn")): ((a.get("delivery") or {}).get("voice") or {}).get("sections")
            for s, report in reports for a in report["answers"]
            if any(x.get("advice") for x in ((a.get("delivery") or {}).get("voice") or {}).get("sections") or [])}
    # Pass 1: stats and voice numbers, no baseline yet.
    for s, report in reports:
        turns = db.list_turns(s["id"])
        _fill_words(s["id"], turns)
        targets = brief.targets(brief.report_rubric(report)["categories"])  # older reports: today's targets
        delivery.answer_delivery(report["answers"], turns, db.ANSWERS_DIR / s["id"], targets=targets,
                                 no_target=brief.untimed_stations(feedback.session_brief(s)))
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
        face_base = db.face_baseline(exclude_session=s["id"])
        turns = db.list_turns(s["id"])
        evidence = voice.turn_evidence(turns, db.ANSWERS_DIR / s["id"], base)  # sections and words only, never advice
        for ans in report["answers"]:
            d = ans.get("delivery")
            if d:
                d.update(delivery.voice_fields(d.get("voice"), base))
                if d.get("voice"):
                    old = kept.get((s["id"], ans.get("question_turn")))
                    d["voice"]["sections"] = old if old else voice.answer_sections(
                        delivery.answer_turns(ans, report["answers"], turns), evidence, ans.get("voice_advice"))
                d.update(delivery.add_quotes(delivery.face_fields(d.get("face"), face_base), delivery.answer_turns(ans, report["answers"], turns)))
                flagged += bool(d["voice_flags"] or d.get("face_flags"))
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
