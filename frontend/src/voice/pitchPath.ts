// Turn the per-frame pitch track into something drawable: smoothing, gaps, runs, y range. Pure.
import { percentile, type Pitch } from './selection.ts'

/** 5-frame median over the pitched frames in the window; unpitched frames stay null. Display only. */
export function medianSmooth(p: Pitch, radius = 2): Pitch {
  return p.map((v, i) => {
    if (v == null) return null
    const w: number[] = []
    for (let j = Math.max(0, i - radius); j <= Math.min(p.length - 1, i + radius); j++) {
      const x = p[j]
      if (x != null) w.push(x)
    }
    w.sort((a, b) => a - b)
    return w[Math.floor(w.length / 2)]
  })
}

export interface Pt {
  i: number
  st: number
}

/**
 * Polyline runs: unpitched gaps of `bridge` frames or fewer (60 ms) are bridged, longer gaps break the line
 * (never drawn at zero), and runs under `minRun` pitched frames are dropped.
 */
export function pitchRuns(p: Pitch, bridge = 2, minRun = 3): Pt[][] {
  const sm = medianSmooth(p)
  const runs: Pt[][] = []
  let cur: Pt[] = []
  let last = -1
  for (let i = 0; i < sm.length; i++) {
    const v = sm[i]
    if (v == null) continue
    if (cur.length && i - last - 1 > bridge) {
      runs.push(cur)
      cur = []
    }
    cur.push({ i, st: v })
    last = i
  }
  if (cur.length) runs.push(cur)
  return runs.filter((r) => r.length >= minRun)
}

/** Auto y range: 1st-99th percentile of pitched frames, +-2 st, widened to even numbers and at least 4 st tall. */
export function yRangeOf(p: Pitch): [number, number] {
  const vals = p.filter((v): v is number => v != null).sort((a, b) => a - b)
  if (vals.length === 0) return [-4, 4]
  let lo = Math.floor((percentile(vals, 1) - 2) / 2) * 2
  let hi = Math.ceil((percentile(vals, 99) + 2) / 2) * 2
  if (hi - lo < 4) {
    lo -= 2
    hi += 2
  }
  return [lo, hi]
}

/** Union of two ranges, for drawing an old and a new answer on the same scale. */
export const unionRange = (a: [number, number], b: [number, number]): [number, number] => [Math.min(a[0], b[0]), Math.max(a[1], b[1])]

/** Gridline values every `step` st inside [lo, hi]. */
export function gridlines(lo: number, hi: number, step = 2): number[] {
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v)
  return out
}
