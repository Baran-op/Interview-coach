import { FaceLandmarker, FilesetResolver, type Category } from '@mediapipe/tasks-vision'
import { answerStats, listenCentre, poseFromMatrix, type FaceStats, type FrameSample } from './stats'

/**
 * Reads the webcam stream locally and reduces each sampled frame to a few numbers (head pose, gaze and
 * expression shapes). Video frames are never sent or stored; only the per-answer stats leave this class.
 */

const PREF_KEY = 'faceTracking'
const MODEL_URL = '/models/face_landmarker.task'
const WASM_URL = '/mediapipe'

const EXPR_SHAPES = ['browInnerUp', 'browOuterUpLeft', 'browOuterUpRight', 'browDownLeft', 'browDownRight',
  'cheekSquintLeft', 'cheekSquintRight', 'mouthSmileLeft', 'mouthSmileRight']

export const FPS = 8
const LOG_EVERY_MS = 10000

/** True if the model file is present (Vite answers missing files with index.html). */
export async function faceModelAvailable(): Promise<boolean> {
  try {
    const res = await fetch(MODEL_URL, { method: 'HEAD' })
    return res.ok && !(res.headers.get('content-type') ?? '').includes('text/html')
  } catch {
    return false
  }
}

/** The Setup toggle. On unless switched off; it only has an effect when the model exists. */
export function getFaceTracking(): boolean {
  try {
    return localStorage.getItem(PREF_KEY) !== 'off'
  } catch {
    return true
  }
}

export function setFaceTracking(on: boolean) {
  try {
    localStorage.setItem(PREF_KEY, on ? 'on' : 'off')
  } catch {
    /* not persisted */
  }
}

export class FaceTracker {
  private video: HTMLVideoElement
  private timer: number
  private segment: 'listen' | 'answer' | null = null
  private segStart = 0
  private frames: FrameSample[] = []
  private listenFrames: FrameSample[] = []
  private lastT = -1
  private frameMs = 0
  private frameCount = 0
  private lastLog = performance.now()
  private busy = false

  private landmarker: FaceLandmarker
  /** ms on the session clock (pauses excluded); it stands still while paused. */
  private clock: () => number

  private constructor(landmarker: FaceLandmarker, camera: MediaStream, clock: () => number) {
    this.landmarker = landmarker
    this.clock = clock
    this.video = document.createElement('video')
    this.video.muted = true
    this.video.playsInline = true
    this.video.srcObject = new MediaStream(camera.getVideoTracks()) // own handle; never stops the recorder's tracks
    void this.video.play().catch(() => {})
    this.timer = window.setInterval(() => this.tick(), 1000 / FPS)
  }

  /** Null when the model or WASM can't be loaded, so the caller carries on without face stats. */
  static async create(camera: MediaStream, clock: () => number): Promise<FaceTracker | null> {
    try {
      const fileset = await FilesetResolver.forVisionTasks(WASM_URL)
      const make = (delegate: 'GPU' | 'CPU') =>
        FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate },
          runningMode: 'VIDEO',
          numFaces: 1,
          outputFaceBlendshapes: true,
          outputFacialTransformationMatrixes: true,
        })
      let landmarker: FaceLandmarker
      try {
        landmarker = await make('GPU')
      } catch (e) {
        console.warn('Face tracker: GPU delegate failed, using CPU', e)
        landmarker = await make('CPU')
      }
      return new FaceTracker(landmarker, camera, clock)
    } catch (e) {
      console.warn('Face tracker unavailable', e)
      return null
    }
  }

  /** Mark the start of a stretch: "listen" while the interviewer speaks, "answer" for my answer. */
  startSegment(kind: 'listen' | 'answer') {
    this.segment = kind
    this.segStart = this.clock()
    this.frames = []
    this.lastT = -1
  }

  /** End the current stretch. For an answer, returns its stats (null if nothing was sampled). */
  endSegment(): FaceStats | null {
    const kind = this.segment
    this.segment = null
    const frames = this.frames
    this.frames = []
    if (kind === 'listen') {
      this.listenFrames.push(...frames)
      return null
    }
    if (kind !== 'answer' || !frames.length) return null
    return answerStats(frames, listenCentre(this.listenFrames), this.segStart, this.clock(), 1000 / FPS)
  }

  stop() {
    window.clearInterval(this.timer)
    this.video.srcObject = null
    this.landmarker.close()
    this.frames = []
    this.listenFrames = []
  }

  private tick() {
    if (!this.segment || this.busy || this.video.readyState < 2 || !this.video.videoWidth) return
    const t = this.clock()
    if (t === this.lastT) return // paused: the session clock is not moving
    this.lastT = t
    this.busy = true
    const t0 = performance.now()
    try {
      const r = this.landmarker.detectForVideo(this.video, t0)
      this.frames.push(sample(t, r.faceBlendshapes?.[0]?.categories, r.facialTransformationMatrixes?.[0]?.data))
    } catch (e) {
      console.warn('Face tracker frame failed', e)
    } finally {
      this.busy = false
    }
    this.frameMs += performance.now() - t0
    this.frameCount++
    if (performance.now() - this.lastLog > LOG_EVERY_MS) {
      // Performance check (PLAN-energy.md 2a): over 40 ms on average, or a stuttering avatar, means drop to 5 fps.
      console.info(`[face] ${(this.frameMs / this.frameCount).toFixed(1)} ms/frame over ${this.frameCount} frames`)
      this.frameMs = 0
      this.frameCount = 0
      this.lastLog = performance.now()
    }
  }
}

function sample(t: number, cats: Category[] | undefined, matrix: ArrayLike<number> | undefined): FrameSample {
  if (!cats || !matrix) return { t, found: false, yaw: 0, pitch: 0, eyeDown: 0, eyeSide: 0, eyeUp: 0, expr: [] }
  const b = new Map(cats.map((c) => [c.categoryName, c.score]))
  const g = (n: string) => b.get(n) ?? 0
  const { yaw, pitch } = poseFromMatrix(matrix)
  return {
    t,
    found: true,
    yaw,
    pitch,
    eyeDown: (g('eyeLookDownLeft') + g('eyeLookDownRight')) / 2,
    eyeSide: Math.max((g('eyeLookOutLeft') + g('eyeLookInRight')) / 2, (g('eyeLookInLeft') + g('eyeLookOutRight')) / 2),
    eyeUp: (g('eyeLookUpLeft') + g('eyeLookUpRight')) / 2,
    expr: EXPR_SHAPES.map(g),
  }
}
