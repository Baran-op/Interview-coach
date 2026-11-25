// One shared AudioContext, decoded-buffer cache and sample-accurate playback for the voice graphs.
import { playheadPosition } from './selection.ts'

let ctx: AudioContext | null = null

export function audioContext(): AudioContext {
  if (!ctx) {
    try {
      ctx = new AudioContext({ sampleRate: 16000 }) // the answer WAVs are 16 kHz: no resampling, 4x less memory
    } catch {
      ctx = new AudioContext()
    }
  }
  return ctx
}

interface Entry {
  promise: Promise<AudioBuffer>
  refs: number
}
const buffers = new Map<string, Entry>()

/** Fetch and decode a WAV once; every caller must `releaseBuffer(url)` when done. */
export function loadBuffer(url: string): Promise<AudioBuffer> {
  let e = buffers.get(url)
  if (!e) {
    const promise = fetch(url).then(async (res) => {
      if (!res.ok) throw new Error(res.status === 404 ? 'No audio was saved for this answer.' : `Could not load the audio (${res.status}).`)
      return audioContext().decodeAudioData(await res.arrayBuffer())
    })
    promise.catch(() => buffers.delete(url))
    e = { promise, refs: 0 }
    buffers.set(url, e)
  }
  e.refs++
  return e.promise
}

export function releaseBuffer(url: string) {
  const e = buffers.get(url)
  if (!e) return
  if (--e.refs <= 0) buffers.delete(url)
}

const active = new Set<Playback>()

/** Stop every voice playback (the Feedback tab's video calls this when it starts). */
export function stopAllVoice() {
  for (const p of [...active]) p.stop()
}

export interface PlaybackOptions {
  /** Start position (s). */
  from: number
  /** Stop here (s); omitted plays to the end of the buffer. */
  to?: number
  /** Loop this range (s) instead of stopping. */
  loop?: { start: number; end: number } | null
  /** Called once when playback stops by itself (`natural`) or because something else stopped it. Not called for `stop(true)`. */
  onEnd: (posSeconds: number, natural: boolean) => void
}

export class Playback {
  private src: AudioBufferSourceNode
  private t0: number
  private stopped = false
  private buffer: AudioBuffer
  private opts: PlaybackOptions

  constructor(buffer: AudioBuffer, opts: PlaybackOptions) {
    this.buffer = buffer
    this.opts = opts
    const c = audioContext()
    this.src = c.createBufferSource()
    this.src.buffer = buffer
    this.src.connect(c.destination)
    const { from, to, loop } = opts
    if (loop && loop.end > loop.start) {
      this.src.loop = true
      this.src.loopStart = loop.start
      this.src.loopEnd = loop.end
      this.src.start(0, from)
    } else if (to != null) {
      this.src.start(0, from, Math.max(0.01, to - from))
    } else {
      this.src.start(0, from)
    }
    this.t0 = c.currentTime
    this.src.onended = () => {
      if (this.stopped) return
      this.finish(this.end(), true, false)
    }
    active.add(this)
  }

  private end() {
    return this.opts.to ?? this.buffer.duration
  }

  /** Playhead (s). */
  pos(): number {
    return playheadPosition({ offset: this.opts.from, t0: this.t0, now: audioContext().currentTime, end: this.end(), loop: this.opts.loop })
  }

  private finish(pos: number, natural: boolean, quiet: boolean) {
    this.stopped = true
    active.delete(this)
    try {
      this.src.stop()
    } catch {
      /* already stopped */
    }
    this.src.disconnect()
    if (!quiet) this.opts.onEnd(pos, natural)
  }

  /** Stop where it is. `quiet` skips the onEnd callback (the caller is about to start something else). Returns the position (s). */
  stop(quiet = false): number {
    if (this.stopped) return this.end()
    const p = this.pos()
    this.finish(p, false, quiet)
    return p
  }
}
