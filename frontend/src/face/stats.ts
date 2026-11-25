/**
 * Pure face-stat computation: no DOM, no MediaPipe, no clock. FaceTracker feeds it numbers.
 * Everything here describes behaviour (where the head and eyes pointed, how much the face moved);
 * nothing labels an emotion. Thresholds are starting values from PLAN-energy.md 2a.
 */

/** One sampled camera frame, already reduced to numbers. `t` is ms on the session clock. */
export interface FrameSample {
  t: number
  found: boolean
  yaw: number // degrees, positive = head turned toward the camera's +x
  pitch: number // degrees, positive = head up, negative = down
  eyeDown: number // 0..1, mean of eyeLookDownLeft/Right
  eyeSide: number // 0..1, stronger of the two sideways gaze directions
  eyeUp: number // 0..1
  expr: number[] // expression blendshape scores (upper face and smile)
}

export interface Centre {
  yaw: number
  pitch: number
  eyeDown: number
  /** True when built from enough listen frames (about 3 s). */
  calibrated: boolean
}

export interface AwaySpan {
  start_ms: number
  end_ms: number
  kind: 'down' | 'away'
}

export interface ExprWindow {
  start_ms: number
  value: number
}

/** What is posted with an answer as `face`. Null stats mean "face not found often enough". */
export interface FaceStats {
  t_start_ms: number
  t_end_ms: number
  on_screen_pct: number | null
  looked_down_pct: number | null
  expressiveness: number | null
  face_found_pct: number
  frames: number
  away_spans: AwaySpan[]
  expr_windows: ExprWindow[]
}

export const LIMITS = {
  yawDeg: 12,
  pitchDeg: 10,
  downPitchDeg: 12, // head this far below the listen centre counts as looking down
  downEyeDelta: 0.3, // eyeLookDown this far above the listen centre does too
  gazeAway: 0.6, // strong sideways or upward gaze
  downSpanMs: 3000,
  awaySpanMs: 5000,
  bridgeMs: 500,
  maxSpans: 20,
  windowMs: 5000,
  minCalibrationFrames: 24, // 3 s at 8 fps
  minFoundPct: 50,
  minWindowFrames: 8,
}

export type Label = 'on' | 'down' | 'away' | 'none'

const median = (xs: number[]) => {
  if (!xs.length) return 0
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)

/** Head yaw and pitch in degrees from MediaPipe's column-major 4x4 facial transformation matrix. */
export function poseFromMatrix(m: ArrayLike<number>): { yaw: number; pitch: number } {
  // Column 2 of the rotation is where the face's forward axis points: (m[8], m[9], m[10]).
  const fx = m[8]
  const fy = Math.max(-1, Math.min(1, m[9]))
  const fz = m[10]
  const deg = 180 / Math.PI
  return { yaw: Math.atan2(fx, fz) * deg, pitch: Math.asin(fy) * deg }
}

/** Where "looking at the screen" is for this session: the median pose over frames while the interviewer spoke. */
export function listenCentre(frames: FrameSample[]): Centre {
  const f = frames.filter((x) => x.found)
  return {
    yaw: median(f.map((x) => x.yaw)),
    pitch: median(f.map((x) => x.pitch)),
    eyeDown: median(f.map((x) => x.eyeDown)),
    calibrated: f.length >= LIMITS.minCalibrationFrames,
  }
}

export function labelFrame(f: FrameSample, c: Centre): Label {
  if (!f.found) return 'none'
  const dPitch = f.pitch - c.pitch
  const down = dPitch < -LIMITS.downPitchDeg || f.eyeDown - c.eyeDown > LIMITS.downEyeDelta
  if (down) return 'down'
  const off =
    Math.abs(f.yaw - c.yaw) > LIMITS.yawDeg ||
    Math.abs(dPitch) > LIMITS.pitchDeg ||
    f.eyeSide >= LIMITS.gazeAway ||
    f.eyeUp >= LIMITS.gazeAway
  return off ? 'away' : 'on'
}

/** Mean standard deviation of each expression shape over the frames, times 100. Null with fewer than 2 frames. */
export function expressiveness(frames: FrameSample[]): number | null {
  const f = frames.filter((x) => x.found && x.expr.length)
  if (f.length < 2) return null
  const dims = f[0].expr.length
  let total = 0
  for (let d = 0; d < dims; d++) {
    const xs = f.map((x) => x.expr[d] ?? 0)
    const mu = mean(xs)
    total += Math.sqrt(mean(xs.map((x) => (x - mu) ** 2)))
  }
  return (total / dims) * 100
}

/**
 * Off-screen stretches worth showing. Looks of under 0.5 s are bridged (a short return to the screen
 * does not split one look into two). Down for 3 s or more is "down"; off to the side or above for 5 s
 * or more is "away"; shorter ones are never flagged. Frames with no face end a stretch.
 */
export function awaySpans(frames: FrameSample[], labels: Label[], frameMs: number, endMs: number): AwaySpan[] {
  const l = [...labels]
  // Bridge short 'on' dips between two off-screen frames, taking the earlier label.
  for (let i = 0; i < l.length; i++) {
    if (l[i] !== 'on' || i === 0 || (l[i - 1] !== 'down' && l[i - 1] !== 'away')) continue
    let j = i
    while (j < l.length && l[j] === 'on') j++
    if (j < l.length && (l[j] === 'down' || l[j] === 'away') && frames[j].t - frames[i].t < LIMITS.bridgeMs) {
      for (let k = i; k < j; k++) l[k] = l[i - 1]
    }
    i = j - 1
  }
  const spans: AwaySpan[] = []
  let i = 0
  while (i < l.length) {
    const kind = l[i]
    if (kind !== 'down' && kind !== 'away') {
      i++
      continue
    }
    let j = i
    while (j + 1 < l.length && l[j + 1] === kind) j++
    const start = frames[i].t
    const end = Math.min(endMs, frames[j].t + frameMs)
    if (end - start >= (kind === 'down' ? LIMITS.downSpanMs : LIMITS.awaySpanMs)) {
      spans.push({ start_ms: Math.round(start), end_ms: Math.round(end), kind })
    }
    i = j + 1
  }
  return spans.slice(0, LIMITS.maxSpans)
}

/** The per-answer numbers. `frames` are the samples taken during the answer segment. */
export function answerStats(frames: FrameSample[], centre: Centre, tStart: number, tEnd: number, frameMs: number): FaceStats {
  const found = frames.filter((f) => f.found)
  const foundPct = frames.length ? (found.length / frames.length) * 100 : 0
  const base = {
    t_start_ms: Math.round(tStart),
    t_end_ms: Math.round(tEnd),
    face_found_pct: Math.round(foundPct * 10) / 10,
    frames: frames.length,
  }
  if (!frames.length || foundPct < LIMITS.minFoundPct) {
    return { ...base, on_screen_pct: null, looked_down_pct: null, expressiveness: null, away_spans: [], expr_windows: [] }
  }
  const labels = frames.map((f) => labelFrame(f, centre))
  const share = (k: Label) => (labels.filter((x) => x === k).length / found.length) * 100
  const windows: ExprWindow[] = []
  for (let w = tStart; w < tEnd; w += LIMITS.windowMs) {
    const inWin = frames.filter((f) => f.t >= w && f.t < w + LIMITS.windowMs)
    if (inWin.filter((f) => f.found).length < LIMITS.minWindowFrames) continue
    const v = expressiveness(inWin)
    if (v !== null) windows.push({ start_ms: Math.round(w), value: Math.round(v * 100) / 100 })
  }
  const expr = expressiveness(frames)
  return {
    ...base,
    on_screen_pct: Math.round(share('on') * 10) / 10,
    looked_down_pct: Math.round(share('down') * 10) / 10,
    expressiveness: expr === null ? null : Math.round(expr * 100) / 100,
    away_spans: awaySpans(frames, labels, frameMs, tEnd),
    expr_windows: windows,
  }
}
