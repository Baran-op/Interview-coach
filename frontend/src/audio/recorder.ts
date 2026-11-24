export type RecordMode = 'webcam' | 'audio' | 'off'

const PREF_KEY = 'recordMode'

export function getRecordMode(): RecordMode {
  try {
    const v = localStorage.getItem(PREF_KEY)
    return v === 'audio' || v === 'off' ? v : 'webcam'
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

/**
 * Records the whole session to one WebM file: my mic and the interviewer's
 * voice mixed with the Web Audio API, plus the webcam (if enabled).
 *
 * The recording mic is separate from the VAD's mic, so it keeps recording while
 * the VAD is off (when the interviewer is talking).
 */
export class SessionRecorder {
  readonly camera: MediaStream | null
  readonly mode: 'webcam' | 'audio'
  private mic: MediaStream
  private recorder: MediaRecorder
  private chunks: Blob[] = []
  private dest: MediaStreamAudioDestinationNode
  private source: AudioNode
  private micNode: MediaStreamAudioSourceNode

  private constructor(opts: {
    camera: MediaStream | null
    mic: MediaStream
    recorder: MediaRecorder
    dest: MediaStreamAudioDestinationNode
    source: AudioNode
    micNode: MediaStreamAudioSourceNode
  }) {
    this.camera = opts.camera
    this.mode = opts.camera ? 'webcam' : 'audio'
    this.mic = opts.mic
    this.recorder = opts.recorder
    this.dest = opts.dest
    this.source = opts.source
    this.micNode = opts.micNode
    this.recorder.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data)
    }
  }

  /**
   * @param ctx the AudioContext the interviewer plays through
   * @param interviewerOut the node carrying the interviewer's voice
   * Throws if the microphone can't be opened.
   */
  static async create(ctx: AudioContext, interviewerOut: AudioNode, mode: 'webcam' | 'audio'): Promise<SessionRecorder> {
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    let camera: MediaStream | null = null
    if (mode === 'webcam') {
      try {
        camera = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 24 } },
        })
      } catch (e) {
        console.warn('Camera unavailable, recording audio only', e)
      }
    }
    const dest = ctx.createMediaStreamDestination()
    interviewerOut.connect(dest)
    const micNode = ctx.createMediaStreamSource(mic)
    micNode.connect(dest) // into the recording only, not the speakers

    const tracks = [...(camera?.getVideoTracks() ?? []), ...dest.stream.getAudioTracks()]
    const types = camera ? VIDEO_TYPES : AUDIO_TYPES
    const mimeType = types.find((t) => MediaRecorder.isTypeSupported(t)) ?? ''
    const recorder = new MediaRecorder(new MediaStream(tracks), {
      mimeType,
      videoBitsPerSecond: 1_000_000, // ~7.5 MB per minute at 640x480
      audioBitsPerSecond: 96_000,
    })
    return new SessionRecorder({ camera, mic, recorder, dest, source: interviewerOut, micNode })
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
    this.camera?.getTracks().forEach((t) => t.stop())
    this.mic.getTracks().forEach((t) => t.stop())
    try {
      this.source.disconnect(this.dest)
      this.micNode.disconnect()
    } catch {
      /* context closed */
    }
  }
}
