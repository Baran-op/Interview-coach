/** What goes in the video track: me, the avatar, or both side by side. */
export type RecordMode = 'webcam' | 'avatar' | 'both' | 'audio' | 'off'

const PREF_KEY = 'recordMode'

export function getRecordMode(): RecordMode {
  try {
    const v = localStorage.getItem(PREF_KEY)
    return v === 'audio' || v === 'off' || v === 'avatar' || v === 'both' ? v : 'webcam'
  } catch {
    return 'webcam'
  }
}

export function setRecordMode(mode: RecordMode) {
  try {
    localStorage.setItem(PREF_KEY, mode)
  } catch {
    /* not persisted */
  }
}

const VIDEO_TYPES = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
const AUDIO_TYPES = ['audio/webm;codecs=opus', 'audio/webm']

/** Draws the avatar and the webcam side by side into one canvas. */
class SideBySide {
  readonly stream: MediaStream
  private timer: number
  private avatarVideo: HTMLVideoElement
  private camVideo: HTMLVideoElement

  constructor(avatarCanvas: HTMLCanvasElement, camera: MediaStream, fps = 24) {
    const canvas = document.createElement('canvas')
    canvas.width = 1280
    canvas.height = 480
    const g = canvas.getContext('2d')!
    // Read the WebGL canvas through its own stream: drawImage() on a WebGL
    // canvas can come out blank between frames.
    this.avatarVideo = videoFor(avatarCanvas.captureStream(fps))
    this.camVideo = videoFor(camera)
    const draw = () => {
      g.fillStyle = '#1e2126'
      g.fillRect(0, 0, canvas.width, canvas.height)
      drawCover(g, this.avatarVideo, 0, 0, 640, 480, false)
      drawCover(g, this.camVideo, 640, 0, 640, 480, false) // unmirrored: text reads correctly
    }
    this.timer = window.setInterval(draw, 1000 / fps) // setInterval: keeps going in background tabs
    this.stream = canvas.captureStream(fps)
  }

  stop() {
    window.clearInterval(this.timer)
    for (const v of [this.avatarVideo, this.camVideo]) {
      ;(v.srcObject as MediaStream | null)?.getTracks().forEach((t) => t.stop())
      v.srcObject = null
    }
    this.stream.getTracks().forEach((t) => t.stop())
  }
}

function videoFor(stream: MediaStream): HTMLVideoElement {
  const v = document.createElement('video')
  v.muted = true
  v.playsInline = true
  v.srcObject = stream
  void v.play().catch(() => {})
  return v
}

function drawCover(g: CanvasRenderingContext2D, v: HTMLVideoElement, x: number, y: number, w: number, h: number, mirror: boolean) {
  const vw = v.videoWidth
  const vh = v.videoHeight
  if (!vw || !vh) return
  const scale = Math.max(w / vw, h / vh)
  const sw = w / scale
  const sh = h / scale
  g.save()
  if (mirror) {
    g.translate(x + w, y)
    g.scale(-1, 1)
    g.drawImage(v, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, w, h)
  } else {
    g.drawImage(v, (vw - sw) / 2, (vh - sh) / 2, sw, sh, x, y, w, h)
  }
  g.restore()
}

/**
 * Records the whole session to one WebM file: my mic and the interviewer's
 * voice mixed with the Web Audio API, plus a video track: the webcam, the
 * avatar canvas, or both side by side.
 *
 * The recording mic is separate from the VAD's mic, so it keeps recording while
 * the VAD is off (when the interviewer is talking).
 */
export class SessionRecorder {
  readonly camera: MediaStream | null
  /** What is actually being recorded (may fall back, e.g. no camera). */
  readonly mode: Exclude<RecordMode, 'off'>
  private mic: MediaStream
  private recorder: MediaRecorder
  private chunks: Blob[] = []
  private dest: MediaStreamAudioDestinationNode
  private sources: AudioNode[]
  private micNode: MediaStreamAudioSourceNode
  private extra: { stop(): void }[]

  private constructor(opts: {
    camera: MediaStream | null
    mode: Exclude<RecordMode, 'off'>
    mic: MediaStream
    recorder: MediaRecorder
    dest: MediaStreamAudioDestinationNode
    sources: AudioNode[]
    micNode: MediaStreamAudioSourceNode
    extra: { stop(): void }[]
  }) {
    this.camera = opts.camera
    this.mode = opts.mode
    this.mic = opts.mic
    this.recorder = opts.recorder
    this.dest = opts.dest
    this.sources = opts.sources
    this.micNode = opts.micNode
    this.extra = opts.extra
    this.recorder.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data)
    }
  }

  /**
   * @param ctx the AudioContext the interviewer plays through
   * @param voices nodes carrying the interviewer's voice (player and/or avatar)
   * @param avatarCanvas the avatar's canvas, for the 'avatar' and 'both' modes
   * Throws if the microphone can't be opened.
   */
  static async create(
    ctx: AudioContext,
    voices: AudioNode[],
    mode: Exclude<RecordMode, 'off'>,
    avatarCanvas: HTMLCanvasElement | null = null,
  ): Promise<SessionRecorder> {
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    // Fall back when the avatar is missing.
    if (!avatarCanvas && mode === 'avatar') mode = 'audio'
    if (!avatarCanvas && mode === 'both') mode = 'webcam'

    let camera: MediaStream | null = null
    if (mode === 'webcam' || mode === 'both') {
      try {
        camera = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 24 } },
        })
      } catch (e) {
        console.warn('Camera unavailable', e)
        mode = mode === 'both' ? 'avatar' : 'audio'
      }
    }

    const extra: { stop(): void }[] = []
    let video: MediaStreamTrack[] = []
    if (mode === 'webcam' && camera) {
      video = camera.getVideoTracks()
    } else if (mode === 'avatar' && avatarCanvas) {
      const s = avatarCanvas.captureStream(24)
      extra.push({ stop: () => s.getTracks().forEach((t) => t.stop()) })
      video = s.getVideoTracks()
    } else if (mode === 'both' && avatarCanvas && camera) {
      const sbs = new SideBySide(avatarCanvas, camera)
      extra.push(sbs)
      video = sbs.stream.getVideoTracks()
    }

    const dest = ctx.createMediaStreamDestination()
    voices.forEach((v) => v.connect(dest))
    const micNode = ctx.createMediaStreamSource(mic)
    micNode.connect(dest) // into the recording only, not the speakers

    const tracks = [...video, ...dest.stream.getAudioTracks()]
    const types = video.length ? VIDEO_TYPES : AUDIO_TYPES
    const mimeType = types.find((t) => MediaRecorder.isTypeSupported(t)) ?? ''
    const recorder = new MediaRecorder(new MediaStream(tracks), {
      mimeType,
      videoBitsPerSecond: mode === 'both' ? 1_600_000 : 1_000_000, // ~7.5-12 MB per minute
      audioBitsPerSecond: 96_000,
    })
    return new SessionRecorder({ camera, mode, mic, recorder, dest, sources: voices, micNode, extra })
  }

  start() {
    this.chunks = []
    this.recorder.start(1000)
  }

  pause() {
    if (this.recorder.state === 'recording') this.recorder.pause()
  }

  resume() {
    if (this.recorder.state === 'paused') this.recorder.resume()
  }

  /** Stop recording, release the camera and mic, and return the file. */
  stop(): Promise<Blob> {
    return new Promise((resolve) => {
      const finish = () => {
        this.release()
        resolve(new Blob(this.chunks, { type: this.recorder.mimeType || 'video/webm' }))
      }
      if (this.recorder.state === 'inactive') return finish()
      this.recorder.addEventListener('stop', finish, { once: true })
      this.recorder.stop()
    })
  }

  /** Release the camera and mic without keeping the recording. */
  release() {
    if (this.recorder.state !== 'inactive') {
      try {
        this.recorder.stop()
      } catch {
        /* already stopped */
      }
    }
    this.extra.forEach((x) => x.stop())
    this.camera?.getTracks().forEach((t) => t.stop())
    this.mic.getTracks().forEach((t) => t.stop())
    for (const s of this.sources) {
      try {
        s.disconnect(this.dest)
      } catch {
        /* context closed */
      }
    }
    try {
      this.micNode.disconnect()
    } catch {
      /* context closed */
    }
  }
}
