"""Calibrate the flat-section thresholds on your own recordings (PLAN-voice.md, V3). Spends no Claude requests.

    python -m scripts.voice_windows [--dir data/answers] [--labels labels.csv] [--clips data/calibration]
    python -m scripts.voice_windows --score [--yin 0.15,0.20]

Step 1 (no flags): reads every WAV under --dir (interview answers and Drill attempts), prints the 10 s window
spread percentiles over all windows, per answer and per labelled group, then writes the 10 flattest and 10
liveliest windows as WAV clips plus ``calibration.csv`` to --clips (default data/calibration, git-ignored).
Listen to each clip and fill ``flat_heard`` with y or n.

Step 2 (--score): reads the filled CSV and reports, for each candidate threshold (2.0 / 2.5 / 3.0 st absolute;
0.5 / 0.6 / 0.7 x your usual window spread), how often it agrees with your ears, plus the share of windows it
flags in each group (the "varied" group should stay near 0, the "flat" one near 100). ``--yin 0.15,0.20`` repeats
the pitched-frame coverage and the window agreement at each YIN threshold. Changing the real YIN threshold moves
stored ``pitch_range_st``: it is a separate decision with a backfill (``scripts.backfill_delivery``).

Groups come from ``--labels`` (CSV ``file,group``; file is a path or a basename like ``<attempt>.wav``) or, for
Drill attempts, from the first word of the attempt's answer text: normal..., flat... or monotone..., varied... or
lively.... Everything else is group ``interview`` / ``ungrouped``. This tool only measures: the constants in
``backend/voice.py`` stay PROVISIONAL until you've listened and chosen them.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import delivery, voice  # noqa: E402

ABSOLUTE = (2.0, 2.5, 3.0)
RELATIVE = (0.5, 0.6, 0.7)
CLIPS = 10
COLUMNS = ("clip", "file", "start", "end", "spread", "pitched_frames", "flat_heard")
_FIRST_WORD = {"normal": "normal", "flat": "flat", "monotone": "flat", "varied": "varied", "lively": "varied"}


def group_from_text(text: str | None) -> str | None:
    """The calibration group named by an attempt's first word ("normal one", "flat two", "varied three")."""
    m = re.match(r"\W*([a-z]+)", (text or "").lower())
    return _FIRST_WORD.get(m.group(1)) if m else None


def percentiles(values) -> dict | None:
    v = [x for x in values if x is not None]
    if not v:
        return None
    p10, p50, p90 = np.percentile(v, [10, 50, 90])
    return {"n": len(v), "p10": round(float(p10), 2), "p50": round(float(p50), 2), "p90": round(float(p90), 2)}


def measure(path, yin: float | None = None) -> dict | None:
    """Window spreads of one WAV (None when unreadable): {path, seconds, windows, voiced_frames, pitched_frames}."""
    wav = delivery.read_wav(path)
    if wav is None:
        return None
    old = delivery._YIN_THRESHOLD
    if yin is not None:
        delivery._YIN_THRESHOLD = yin
    try:
        track = delivery.pitch_track(*wav)
    finally:
        delivery._YIN_THRESHOLD = old
    if track is None:
        return None
    return {"path": str(path), "seconds": len(wav[0]) / wav[1], "track": track, "windows": voice.window_spreads(track),
            "voiced_frames": int(track["voiced"].sum()), "pitched_frames": int((~np.isnan(track["f0_hz"])).sum())}


def pick_clips(rows: list[dict], n: int = CLIPS) -> list[dict]:
    """The ``n`` flattest and ``n`` liveliest windows, never two overlapping in one file. Rows: {path, a, b, spread_st, pitched}."""
    def take(ordered, taken=()):
        chosen: list[dict] = []
        for r in ordered:
            if all(c["path"] != r["path"] or r["b"] <= c["a"] or r["a"] >= c["b"] for c in [*taken, *chosen]):
                chosen.append(r)
            if len(chosen) == n:
                break
        return chosen

    flat = take(sorted(rows, key=lambda r: (r["spread_st"], r["path"], r["a"])))
    lively = take(sorted(rows, key=lambda r: (-r["spread_st"], r["path"], r["a"])), flat)
    return [*flat, *lively]


def agreement(rows: list[dict], threshold: float) -> dict:
    """How a threshold compares with your listening: rows carry spread_st and heard (True = flat, False = not)."""
    rows = [r for r in rows if r.get("heard") is not None]
    if not rows:
        return {"n": 0, "agree": None, "flat_found": None, "false_flags": None}
    pred = [r["spread_st"] < threshold for r in rows]
    heard = [r["heard"] for r in rows]
    flat_n, not_n = sum(heard), len(heard) - sum(heard)
    return {
        "n": len(rows),
        "agree": round(sum(p == h for p, h in zip(pred, heard)) / len(rows), 2),
        "flat_found": round(sum(p and h for p, h in zip(pred, heard)) / flat_n, 2) if flat_n else None,
        "false_flags": round(sum(p and not h for p, h in zip(pred, heard)) / not_n, 2) if not_n else None,
    }


def flagged_share(spreads: list[float], threshold: float) -> float | None:
    return round(sum(s < threshold for s in spreads) / len(spreads), 2) if spreads else None


def thresholds(usual: float | None) -> list[tuple[str, float]]:
    out = [(f"{t:g} st", t) for t in ABSOLUTE]
    if usual:
        out += [(f"{r:g} x usual ({usual:.2f} st)", r * usual) for r in RELATIVE]
    return out


def discover(root: Path, labels_file: Path | None = None) -> dict[Path, str]:
    """Every WAV under ``root`` mapped to its group."""
    labels: dict[str, str] = {}
    if labels_file and labels_file.exists():
        with labels_file.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                labels[r["file"].strip()] = r["group"].strip().lower()
    attempts: dict[str, str] = {}
    try:  # Drill attempts: the first word of the answer text names the group
        from backend import db

        if db.DB_PATH.exists():
            attempts = {a["id"]: g for a in db.list_attempts_all() if (g := group_from_text(a.get("answer_text")))}
    except Exception:  # a missing or locked db only costs the auto labels
        pass
    out = {}
    for p in sorted(root.rglob("*.wav")):
        g = labels.get(str(p)) or labels.get(p.name)
        if g is None and p.parent.name == "drill":
            g = attempts.get(p.stem)
        out[p] = g or ("ungrouped" if p.parent.name == "drill" else "interview")
    return out


def write_clip(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _fmt(p: dict | None) -> str:
    return "no windows" if not p else f"n={p['n']}  p10={p['p10']}  median={p['p50']}  p90={p['p90']}"


def step_one(args) -> None:
    files = discover(Path(args.dir), Path(args.labels) if args.labels else None)
    measured = {}
    for p, g in files.items():
        m = measure(p)
        if m:
            measured[p] = (g, m)
    rows = [{"path": str(p), "group": g, "a": w["a"], "b": w["b"], "spread_st": w["spread_st"], "pitched": w["pitched"]}
            for p, (g, m) in measured.items() for w in m["windows"]]
    print(f"{len(measured)} WAVs read, {len(rows)} windows (10 s, pitched >= {voice.MIN_PITCHED} frames)\n")
    for p, (g, m) in measured.items():
        cov = 100 * m["pitched_frames"] / m["voiced_frames"] if m["voiced_frames"] else 0
        print(f"{str(p):62} {g:10} {m['seconds']:6.1f} s  pitched {cov:3.0f}% of voiced  {_fmt(percentiles([w['spread_st'] for w in m['windows']]))}")
    print()
    for g in sorted({g for g, _ in measured.values()}):
        print(f"group {g:10} {_fmt(percentiles([r['spread_st'] for r in rows if r['group'] == g]))}")
    print(f"all windows       {_fmt(percentiles([r['spread_st'] for r in rows]))}")
    if not rows:
        return
    out = Path(args.clips)
    csv_path = out / "calibration.csv"
    if csv_path.exists() and any((r.get("flat_heard") or "").strip() for r in csv.DictReader(csv_path.open(encoding="utf-8"))) and not args.force:
        sys.exit(f"\n{csv_path} already has your answers; pass --force to overwrite it, or --score to use it.")
    out.mkdir(parents=True, exist_ok=True)
    picked = pick_clips(rows)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(COLUMNS)
        for i, r in enumerate(picked, 1):
            x, rate = delivery.read_wav(r["path"])
            a_s, b_s = r["a"] * delivery.FRAME_S, r["b"] * delivery.FRAME_S
            clip = f"clip_{i:02d}.wav"
            write_clip(out / clip, x[int(a_s * rate) : int(b_s * rate)], rate)
            wr.writerow([clip, r["path"], f"{a_s:.2f}", f"{b_s:.2f}", f"{r['spread_st']:.2f}", r["pitched"], ""])
    print(f"\nWrote {len(picked)} clips and {csv_path}. Listen, fill flat_heard with y or n, then run with --score.")


def step_score(args) -> None:
    csv_path = Path(args.clips) / "calibration.csv"
    if not csv_path.exists():
        sys.exit(f"{csv_path} not found: run without --score first.")
    labelled = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    files = discover(Path(args.dir), Path(args.labels) if args.labels else None)
    yins = [None] if not args.yin else [float(v) for v in args.yin.split(",")]
    for yin in yins:
        print(f"=== YIN threshold {yin if yin is not None else delivery._YIN_THRESHOLD} ===")
        measured = {p: (g, m) for p, g in files.items() if (m := measure(p, yin))}
        spreads = [w["spread_st"] for _, m in measured.values() for w in m["windows"]]
        usual = float(np.median(spreads)) if spreads else None
        cov = [m["pitched_frames"] / m["voiced_frames"] for _, m in measured.values() if m["voiced_frames"]]
        print(f"pitched coverage (share of voiced frames): {100 * float(np.mean(cov)):.0f}% mean over {len(cov)} answers" if cov else "no answers")
        rows = []
        for r in labelled:
            heard = (r.get("flat_heard") or "").strip().lower()[:1]
            tr = next((m["track"] for p, (_, m) in measured.items() if str(p) == r["file"]), None)
            if heard not in ("y", "n") or tr is None:
                continue
            a, b = round(float(r["start"]) / delivery.FRAME_S), round(float(r["end"]) / delivery.FRAME_S)
            st = delivery.to_semitones(tr["f0_hz"][a:b], float(np.nanmedian(tr["f0_hz"])))
            st = st[~np.isnan(st)]
            if len(st) < voice.MIN_PITCHED:
                continue
            rows.append({"spread_st": float(np.percentile(st, 90) - np.percentile(st, 10)), "heard": heard == "y"})
        print(f"{len(rows)} listened windows. usual window spread (median of all) = {usual:.2f} st" if usual else "no windows")
        for name, thr in thresholds(usual):
            a = agreement(rows, thr)
            share = {g: flagged_share([w["spread_st"] for gg, m in measured.values() if gg == g for w in m["windows"]], thr)
                     for g in sorted({g for g, _ in measured.values()})}
            print(f"  {name:28} threshold {thr:.2f}  agree={a['agree']}  flat found={a['flat_found']}  false flags={a['false_flags']}  "
                  f"windows flagged by group: {share}")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default="data/answers", help="folder searched recursively for .wav files")
    ap.add_argument("--labels", help="CSV with file,group columns (normal / flat / varied)")
    ap.add_argument("--clips", default="data/calibration", help="where clips and calibration.csv go")
    ap.add_argument("--score", action="store_true", help="score thresholds against the flat_heard column")
    ap.add_argument("--yin", help="comma-separated YIN thresholds to compare, e.g. 0.15,0.20 (with --score)")
    ap.add_argument("--force", action="store_true", help="overwrite a calibration.csv that already has answers")
    args = ap.parse_args()
    (step_score if args.score else step_one)(args)


if __name__ == "__main__":
    main()
