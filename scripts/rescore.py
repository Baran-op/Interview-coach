"""Re-run the report prompt on a stored transcript n times, without saving, and print the score spread.

    python -m scripts.rescore <session_id> --n 3 [--db path/to/interview.db]

Spends n Claude requests, so run it by hand only. Targets: overall spread <= 0.3, per answer <= 0.5.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import brief, db, feedback  # noqa: E402


def spread(values: list[float]) -> float:
    return round(max(values) - min(values), 2) if values else 0.0


def summarise(reports: list[dict]) -> dict:
    """Spread per answer (matched by question_turn, else by position) and per criterion, plus overall."""
    criteria = [c["key"] for c in brief.report_rubric(reports[0] if reports else None)["criteria"]]
    keyed: dict = {}
    for r in reports:
        for i, a in enumerate(r["answers"]):
            key = a["question_turn"] if a["question_turn"] is not None else f"pos{i}"
            keyed.setdefault(key, {"question": a["question"], "runs": []})["runs"].append(a)
    answers = []
    for key, info in keyed.items():
        runs = info["runs"]
        answers.append({
            "key": key,
            "question": info["question"],
            "runs": len(runs),
            "average_spread": spread([a["average"] for a in runs]),
            "criteria": {c: spread([a["scores"][c] for a in runs if c in a["scores"]]) for c in criteria},
        })
    overall = [r["overall_score"] for r in reports]
    return {"overall": overall, "overall_spread": spread(overall), "answers": answers, "criteria": criteria}


async def run(session_id: str, n: int) -> list[dict]:
    session = db.get_session(session_id)
    if not session:
        raise SystemExit(f"No session {session_id}")
    pack = db.get_pack(session["pack_id"]) or {}
    turns = db.list_turns(session_id)
    if not any(t["speaker"] == "candidate" for t in turns):
        raise SystemExit("That session has no answers")
    snapshot = feedback.session_brief(session)  # the session's own rubric, as the stored report used
    system, transcript = feedback._system_prompt(pack, brief=snapshot), feedback._transcript(turns)
    schema = feedback.report_schema(snapshot)
    reports = []
    for i in range(n):
        print(f"run {i + 1}/{n} ...", file=sys.stderr)
        reports.append(feedback.normalise(await feedback._ask_claude(system, transcript, schema), turns, snapshot))
    return reports


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_id")
    ap.add_argument("--n", type=int, default=3, help="number of runs (each is one Claude request)")
    ap.add_argument("--db", help="path to interview.db (default: data/interview.db)")
    args = ap.parse_args()
    if args.db:
        db.DB_PATH = Path(args.db)
    reports = asyncio.run(run(args.session_id, max(1, args.n)))
    s = summarise(reports)
    print(f"\nOverall scores: {s['overall']}  spread {s['overall_spread']} (target <= 0.3)")
    print(f"\n{'turn':>5}  {'avg':>5}  " + "  ".join(f"{c[:5]:>5}" for c in s["criteria"]) + "  question")
    for a in s["answers"]:
        flag = " !" if a["average_spread"] > 0.5 else ""
        print(f"{str(a['key']):>5}  {a['average_spread']:>5}  "
              + "  ".join(f"{a['criteria'][c]:>5}" for c in s["criteria"])
              + f"  {a['question'][:50]}{flag}")
    print("\nSpread = max - min across runs (per-answer target <= 0.5, marked !).")


if __name__ == "__main__":
    main()
