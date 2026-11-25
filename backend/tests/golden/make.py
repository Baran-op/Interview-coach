"""Render today's prompts for the golden tests, and (by hand only) regenerate the files.

    python -m backend.tests.golden.make

A golden file should change only on purpose: run this only when a prompt change is meant to
change what Claude sees, and review the diff.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend import brain, drill, feedback, prep
from backend.tests.golden.fixtures import FIXES, HISTORY, PACKS

GOLDEN_DIR = Path(__file__).parent


def _with(pack: dict, **opts) -> dict:
    return {**pack, "options": {**pack["options"], **opts}}


def render_all() -> dict[str, str]:
    """{file name: rendered text} for every golden file."""
    out: dict[str, str] = {}
    for name, pack in PACKS.items():
        for stage in ("screen", "full", "final"):
            for timed in (False, True):
                p = _with(pack, stage=stage, minutes=30 if timed else None)
                for hist_name, hist in (("nohist", None), ("hist", HISTORY)):
                    key = f"{name}-interviewer-{stage}-{'timed' if timed else 'untimed'}-{hist_name}.txt"
                    out[key] = brain.build_system_prompt(p, hist)
        out[f"{name}-feedback.txt"] = feedback._system_prompt(pack)
        out[f"{name}-feedback-fixes.txt"] = feedback._system_prompt(pack, FIXES)
        out[f"{name}-drill.txt"] = drill.system_prompt(pack)
        out[f"{name}-prep.txt"] = prep.system_prompt(pack)
    out["report_schema.json"] = json.dumps(feedback.REPORT_SCHEMA, indent=2, sort_keys=True) + "\n"
    out["drill_schema.json"] = json.dumps(drill.SCHEMA, indent=2, sort_keys=True) + "\n"
    return out


def main() -> None:
    files = render_all()
    for name, text in files.items():
        (GOLDEN_DIR / name).write_text(text, encoding="utf-8")
    print(f"Wrote {len(files)} golden files to {GOLDEN_DIR}")


if __name__ == "__main__":
    main()
