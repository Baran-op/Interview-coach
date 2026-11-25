// Time axis helpers for the voice graph: a view (visible window in ms) and the maths around it. Pure.

export interface View {
  start: number
  end: number
}

/** The tightest zoom: 5 s visible (or the whole turn when it is shorter). */
export const MIN_SPAN_MS = 5000

export const fitView = (total: number): View => ({ start: 0, end: Math.max(1, total) })

/** Keep the span inside [min(MIN_SPAN_MS, total), total] and the window inside [0, total]. */
export function clampView(v: View, total: number): View {
  const t = Math.max(1, total)
  const minSpan = Math.min(MIN_SPAN_MS, t)
  const span = Math.min(t, Math.max(minSpan, v.end - v.start))
  const start = Math.min(Math.max(0, v.start), t - span)
  return { start, end: start + span }
}

/** factor > 1 zooms in, < 1 out; the time under `anchorMs` stays at the same place on screen. */
export function zoomView(v: View, total: number, factor: number, anchorMs: number): View {
  const span = v.end - v.start
  const frac = Math.min(1, Math.max(0, span > 0 ? (anchorMs - v.start) / span : 0.5))
  const next = span / factor
  const start = anchorMs - frac * next
  return clampView({ start, end: start + next }, total)
}

export const panView = (v: View, total: number, deltaMs: number): View =>
  clampView({ start: v.start + deltaMs, end: v.end + deltaMs }, total)

/** Slide the window (not resize it) so `ms` is visible, with a margin at the sides. */
export function revealMs(v: View, total: number, ms: number): View {
  const span = v.end - v.start
  const margin = span * 0.08
  if (ms >= v.start + margin && ms <= v.end - margin) return v
  return clampView({ start: ms - span * 0.2, end: ms - span * 0.2 + span }, total)
}

export const xOfMs = (ms: number, v: View, x0: number, w: number) => x0 + ((ms - v.start) / (v.end - v.start)) * w
export const msOfX = (x: number, v: View, x0: number, w: number) => v.start + ((x - x0) / w) * (v.end - v.start)

/** "m:ss" (whole seconds, rounded down). */
export function fmtClock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** "m:ss.s" */
export function fmtClockTenths(ms: number): string {
  const t = Math.max(0, Math.floor(ms / 100))
  const s = Math.floor(t / 10)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}.${t % 10}`
}

const STEPS_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]

/** A round tick spacing (ms) that gives roughly `target` ticks over `spanMs`. */
export function tickStepMs(spanMs: number, target = 6): number {
  const want = spanMs / 1000 / target
  return (STEPS_S.find((s) => s >= want) ?? 600) * 1000
}

export function ticksIn(v: View, stepMs: number): number[] {
  const out: number[] = []
  for (let t = Math.ceil(v.start / stepMs) * stepMs; t <= v.end; t += stepMs) out.push(t)
  return out
}
