import type { Expression, WordTiming } from '../api'
import { base64ToArrayBuffer } from './wav'

/** One voiced sentence from the backend. */
export interface SpokenSentence {
  text: string
  audioBase64: string | null
  /** Per-word timings from Kokoro (for lip-sync). */
  words?: WordTiming[]
  /** Expression tags, char_index relative to `text`. */
  expressions?: Expression[]
}

/**
 * Something that can say the interviewer's sentences in order: the plain audio
 * player below, or the 3D avatar (src/avatar/Avatar.tsx), which lip-syncs.
 */
export interface Speaker {
  /** Queue a sentence; onStart fires when it starts playing. */
  enqueue(sentence: SpokenSentence, onStart?: () => void): void
  /** Resolves once everything queued so far has finished playing. */
  whenIdle(): Promise<void>
  pause(): void
  resume(): void
  /** Stop and drop everything queued. */
  stop(): void
}

interface Cue {
  at: number // AudioContext time
  fn: () => void
}

/**
 * Plays the interviewer's sentences back to back with no gaps.
 *
 * Sentences arrive one by one while later ones are still being generated, so
 * each is scheduled right after the previous one on the AudioContext clock.
 * Callbacks ("this sentence starts now") run off the same clock, so they stay
 * in sync when playback is paused (the context is suspended).
 *
 * `output` is a GainNode the recorder (Milestone 3) can tap.
 */
export class InterviewerPlayer implements Speaker {
  readonly ctx: AudioContext
  readonly output: GainNode
  private nextStart = 0
  private chain: Promise<void> = Promise.resolve()
  private sources = new Set<AudioBufferSourceNode>()
  private cues: Cue[] = []
  private ticker: number
  private generation = 0

  constructor() {
    this.ctx = new AudioContext()
    this.output = this.ctx.createGain()
    this.output.connect(this.ctx.destination)
    this.ticker = window.setInterval(() => this.tick(), 25)
  }

  private tick() {
    const now = this.ctx.currentTime
    const due = this.cues.filter((c) => c.at <= now)
    if (due.length === 0) return
    this.cues = this.cues.filter((c) => c.at > now)
    for (const c of due) c.fn()
  }

  /** Make sure audio can play (browsers start contexts suspended until a user gesture). */
  async unlock(): Promise<boolean> {
    if (this.ctx.state === 'suspended') {
      try {
        await this.ctx.resume()
      } catch {
        /* needs a gesture */
      }
    }
    return this.ctx.state === 'running'
  }

  /** Queue a sentence; onStart fires when it starts playing. */
  enqueue(sentence: SpokenSentence, onStart?: () => void): void {
    const gen = this.generation
    this.chain = this.chain.then(async () => {
      if (gen !== this.generation) return
      let buffer: AudioBuffer | null = null
      if (sentence.audioBase64) {
        try {
          buffer = await this.ctx.decodeAudioData(base64ToArrayBuffer(sentence.audioBase64))
        } catch (e) {
          console.warn('Could not decode interviewer audio', e)
        }
      }
      if (gen !== this.generation) return
      const startAt = Math.max(this.ctx.currentTime + 0.03, this.nextStart)
      if (buffer) {
        const src = this.ctx.createBufferSource()
        src.buffer = buffer
        src.connect(this.output)
        src.onended = () => this.sources.delete(src)
        src.start(startAt)
        this.sources.add(src)
        this.nextStart = startAt + buffer.duration
      } else {
        this.nextStart = startAt
      }
      if (onStart) this.cues.push({ at: startAt, fn: onStart })
    })
  }

  /** Resolves once everything queued so far has finished playing. */
  async whenIdle(): Promise<void> {
    const gen = this.generation
    await this.chain
    await new Promise<void>((resolve) => {
      const check = () => {
        if (gen !== this.generation || this.ctx.currentTime >= this.nextStart) resolve()
        else window.setTimeout(check, 50)
      }
      check()
    })
  }

  get isPlaying(): boolean {
    return this.ctx.currentTime < this.nextStart
  }

  pause() {
    void this.ctx.suspend()
  }

  resume() {
    void this.ctx.resume()
  }

  /** Stop and drop everything queued. */
  stop() {
    this.generation++
    for (const s of this.sources) {
      try {
        s.stop()
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear()
    this.cues = []
    this.nextStart = 0
    this.chain = Promise.resolve()
  }

  destroy() {
    this.stop()
    window.clearInterval(this.ticker)
    void this.ctx.close()
  }
}
