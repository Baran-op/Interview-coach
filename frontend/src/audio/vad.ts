import { MicVAD } from '@ricky0123/vad-web'
import { concatFloat32 } from './wav'

export interface TurnCallbacks {
  /** My whole answer, 16 kHz mono. `bySilence`: ended by the silence timeout (not Done / Space). */
  onTurn: (audio: Float32Array, bySilence: boolean) => void
  /** finish() was called but nothing usable was recorded. */
  onEmpty?: () => void
  onSpeechStart?: () => void
  onSpeechEnd?: () => void
}

const SAMPLE_RATE = 16000

/**
 * Listens for one answer at a time with Silero VAD (in the browser).
 *
 * - A pause in speech longer than `silenceMs` ends the turn automatically.
 * - finish() ends it right away (the "Done" button, or releasing push-to-talk).
 * - While hold(true) is on (spacebar held), silences don't end the turn.
 * - suspend()/resume() pause mid-answer and keep what was said so far.
 * The mic is fully released (tracks stopped) whenever we are not listening.
 */
export class TurnListener {
  private vad: MicVAD | null = null
  private segments: Float32Array[] = []
  private held = false
  private spaceHeld = false
  private collecting = false // finish()/suspend() in progress: just collect segments
  private _listening = false
  private _speaking = false

  private cb: TurnCallbacks
  private silenceMs: number
  private manual: boolean // Done-only mode: silences never end the turn

  constructor(cb: TurnCallbacks, silenceMs = 2000) {
    this.cb = cb
    this.manual = silenceMs === 0
    this.silenceMs = silenceMs || 2000 // still used by the VAD for segmenting
  }

  get listening() {
    return this._listening
  }

  get speaking() {
    return this._speaking
  }

  get hasAudio() {
    return this.segments.length > 0
  }

  async init(): Promise<void> {
    this.vad = await MicVAD.new({
      model: 'v5',
      baseAssetPath: '/vad/',
      onnxWASMBasePath: '/vad/',
      startOnLoad: false,
      redemptionMs: this.silenceMs,
      preSpeechPadMs: 300,
      minSpeechMs: 300,
      submitUserSpeechOnPause: true,
      onSpeechStart: () => {
        this._speaking = true
        this.cb.onSpeechStart?.()
      },
      onVADMisfire: () => {
        this._speaking = false
        this.cb.onSpeechEnd?.()
      },
      onSpeechEnd: (audio: Float32Array) => {
        this._speaking = false
        this.segments.push(audio)
        this.cb.onSpeechEnd?.()
        if (!this.held && !this.collecting && this._listening) {
          // Long enough silence: the answer is over.
          this._listening = false
          this.collecting = true
          void this.pauseVad().finally(() => {
            this.collecting = false
            this.deliver(true)
          })
        }
      },
    })
  }

  /** 0 = Done-only mode (the turn ends only via finish()). */
  setSilenceMs(ms: number) {
    this.manual = ms === 0
    if (this.manual) this.held = true
    else if (this._listening && !this.spaceHeld) this.held = false
    this.silenceMs = ms || 2000
    this.vad?.setOptions({ redemptionMs: this.silenceMs })
  }

  /** Start listening for a new answer. */
  async listen(): Promise<void> {
    if (!this.vad) throw new Error('VAD not initialised')
    this.segments = []
    this.held = this.manual
    this.spaceHeld = false
    this._listening = true
    await this.startVad()
  }

  // start() opens the mic asynchronously; pausing before it finishes throws
  // inside vad-web, so every pause waits for a pending start first.
  private starting: Promise<void> = Promise.resolve()

  private startVad(): Promise<void> {
    this.starting = this.vad!.start()
    return this.starting
  }

  private async pauseVad(): Promise<void> {
    await this.starting.catch(() => {})
    try {
      await this.vad?.pause()
    } catch (e) {
      console.warn('VAD pause failed', e)
    }
  }

  /** Spacebar push-to-talk: while held, pauses don't end the turn. */
  hold(on: boolean) {
    this.spaceHeld = on
    this.held = on || this.manual
  }

  /** End the answer now (Done button / push-to-talk released). */
  async finish(): Promise<void> {
    if (!this.vad || this.collecting) return
    this.held = this.manual
    this.spaceHeld = false
    this.collecting = true
    this._listening = false
    await this.pauseVad() // submits any speech in progress via onSpeechEnd
    this.collecting = false
    this.deliver(false)
  }

  /** Pause mid-answer, keeping what was said so far. */
  async suspend(): Promise<void> {
    if (!this.vad || !this._listening) return
    this.collecting = true
    this._listening = false
    await this.pauseVad()
    this.collecting = false
  }

  /** Resume after suspend(), appending to the same answer. */
  async resume(): Promise<void> {
    if (!this.vad) return
    this._listening = true
    await this.startVad()
  }

  /** Stop listening and throw away anything recorded. */
  async cancel(): Promise<void> {
    this.collecting = true
    this._listening = false
    await this.pauseVad()
    this.collecting = false
    this.segments = []
  }

  private deliver(bySilence: boolean) {
    const audio = concatFloat32(this.segments)
    this.segments = []
    this._speaking = false
    if (audio.length < SAMPLE_RATE * 0.3) this.cb.onEmpty?.()
    else this.cb.onTurn(audio, bySilence)
  }

  async destroy(): Promise<void> {
    await this.starting.catch(() => {})
    try {
      await this.vad?.destroy()
    } catch (e) {
      console.warn('VAD destroy failed', e)
    }
    this.vad = null
  }
}
