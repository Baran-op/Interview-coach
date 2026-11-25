"""Print voice stats for every saved answer WAV, plus the 10th percentile, median and 90th percentile of each.

    python -m scripts.voice_stats [--dir data/answers]

Used to calibrate the voice flags by hand (PLAN-energy.md, 1b): listen to answers from each end of
the pitch range and check the low ones sound flat and the high ones lively.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import delivery  # noqa: E402

KEYS = ("pitch_range_st", "loudness_range_db", "trail_off_pct", "voiced_s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="data/answers", help="folder searched recursively for .wav files")
    ap.add_argument("--json", metavar="FILE", help="also write {path: stats} for every measured WAV to FILE (a before/after snapshot)")
    args = ap.parse_args()
    rows = []
    skipped = 0
    for p in sorted(Path(args.dir).rglob("*.wav")):
        wav = delivery.read_wav(p)
        v = delivery.voice_stats(*wav) if wav else None
        if v is None:
            skipped += 1
            continue
        rows.append((p, v))
        print(f"{str(p):60}" + "  ".join(f"{k}={v[k]}" for k in KEYS))
    if args.json:
        Path(args.json).write_text(json.dumps({str(p): v for p, v in rows}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"\n{len(rows)} answers measured, {skipped} skipped (unreadable or under {delivery.MIN_VOICED_S:.0f} s voiced)")
    for k in KEYS:
        vals = [v[k] for _, v in rows if v[k] is not None]
        if vals:
            p10, med, p90 = np.percentile(vals, [10, 50, 90])
            print(f"{k:20} p10={p10:.2f}  median={med:.2f}  p90={p90:.2f}  (n={len(vals)})")


if __name__ == "__main__":
    main()
