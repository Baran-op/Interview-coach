// Word timings and WAV-time to session-time mapping. Pure.

export interface TimedWord {
  w: string
  start_ms: number
  end_ms: number
}

export interface Seg {
  start_ms: number
  end_ms: number
}

/** After a word ends the highlight stays this long (short pauses), then goes. */
const LINGER_MS = 800

/** Index of the word being said at `ms`: the last word that started at or before it; -1 before the first word or well after the last. */
export function wordIndexAt(words: TimedWord[] | null | undefined, ms: number): number {
  if (!words || words.length === 0 || ms < words[0].start_ms) return -1
  let lo = 0
  let hi = words.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (words[mid].start_ms <= ms) lo = mid
    else hi = mid - 1
  }
  return ms > words[lo].end_ms + LINGER_MS ? -1 : lo
}

/** Words whose midpoint lies inside [start, end]. */
export const wordsInRange = (words: TimedWord[] | null | undefined, start: number, end: number): TimedWord[] =>
  (words ?? []).filter((w) => (w.start_ms + w.end_ms) / 2 >= start && (w.start_ms + w.end_ms) / 2 <= end)

export const joinWords = (ws: TimedWord[]) => ws.map((w) => w.w).join(' ').replace(/\s+/g, ' ').trim()

/** WAV time to session time through the kept segments (their lengths add up to the WAV); outside any segment it snaps to the nearest edge. Null without segments. */
export function wavToSession(ms: number, segments: Seg[] | null | undefined): number | null {
  if (!segments || segments.length === 0) return null
  let acc = 0
  for (const s of segments) {
    const len = s.end_ms - s.start_ms
    if (ms < acc + len) return s.start_ms + Math.max(0, ms - acc)
    acc += len
  }
  return segments[segments.length - 1].end_ms
}
