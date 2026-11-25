// Selection, pitch statistics over a range, and the playhead clock. Pure.

export type Pitch = (number | null)[]

export interface Sel {
  start: number
  end: number
}

/** Selections shorter than this are treated as a click. */
export const MIN_SEL_MS = 80
/** Fewer pitched frames than this and the readout says there isn't enough voiced speech. */
export const MIN_PITCHED_FRAMES = 30

/** numpy's default (linear) percentile of an ascending array; q in 0..100. */
export function percentile(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN
  const pos = ((sorted.length - 1) * q) / 100
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

export function normSel(a: number, b: number, total: number): Sel | null {
  const start = Math.max(0, Math.min(a, b))
  const end = Math.min(total, Math.max(a, b))
  return end - start >= MIN_SEL_MS ? { start, end } : null
}

/** Shift+click: grow the selection to include `ms` (or start one from `anchor`). */
export function extendSel(sel: Sel | null, ms: number, total: number, anchor: number): Sel | null {
  if (!sel) return normSel(anchor, ms, total)
  return normSel(Math.min(sel.start, ms), Math.max(sel.end, ms), total)
}

export interface RangeStats {
  pitchedFrames: number
  /** 10th-90th percentile spread in semitones, or null with under MIN_PITCHED_FRAMES pitched frames. */
  rangeSt: number | null
}

/** Pitch range of the frames whose centre falls in [start, end). */
export function selectionStats(pitch: Pitch, frameMs: number, start: number, end: number): RangeStats {
  const vals: number[] = []
  const i0 = Math.max(0, Math.floor(start / frameMs - 0.5))
  const i1 = Math.min(pitch.length - 1, Math.ceil(end / frameMs))
  for (let i = i0; i <= i1; i++) {
    const c = (i + 0.5) * frameMs
    const v = pitch[i]
    if (v != null && c >= start && c < end) vals.push(v)
  }
  if (vals.length < MIN_PITCHED_FRAMES) return { pitchedFrames: vals.length, rangeSt: null }
  vals.sort((a, b) => a - b)
  return { pitchedFrames: vals.length, rangeSt: percentile(vals, 90) - percentile(vals, 10) }
}

const clk = (ms: number) => {
  const t = Math.max(0, Math.floor(ms / 100))
  const s = Math.floor(t / 10)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}.${t % 10}`
}

/** "0:21.0-0:33.5 (12.5 s) · pitch range 1.6 st · 74 pitched frames", or the too-little-speech line. */
export function selectionReadout(sel: Sel, stats: RangeStats): string {
  const head = `${clk(sel.start)}–${clk(sel.end)} (${((sel.end - sel.start) / 1000).toFixed(1)} s)`
  if (stats.rangeSt == null) return `${head} · too little voiced speech to measure`
  return `${head} · pitch range ${stats.rangeSt.toFixed(1)} st · ${stats.pitchedFrames} pitched frames`
}

export interface PlayClock {
  /** Buffer position (s) at the moment playback began. */
  offset: number
  /** AudioContext time (s) at that moment. */
  t0: number
  now: number
  /** Where a non-looping range ends (s); the buffer end for a plain play. */
  end: number
  loop?: { start: number; end: number } | null
}

/** Where the playhead is (s), including loop wrap-around. */
export function playheadPosition(c: PlayClock): number {
  let p = c.offset + Math.max(0, c.now - c.t0)
  if (c.loop && c.loop.end > c.loop.start && p >= c.loop.end) {
    p = c.loop.start + ((p - c.loop.start) % (c.loop.end - c.loop.start))
    return p
  }
  return Math.min(p, c.end)
}
