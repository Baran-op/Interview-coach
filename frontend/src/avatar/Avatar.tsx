import { useEffect, useRef, useState } from 'react'
import { TalkingHead } from '@met4citizen/talkinghead'
import { LipsyncEn } from '@met4citizen/talkinghead/modules/lipsync-en.mjs'
import type { Expression, WordTiming } from '../api'
import type { Speaker, SpokenSentence } from '../audio/player'
import { base64ToArrayBuffer } from '../audio/wav'

export const AVATAR_URL = '/avatars/interviewer.glb'

/** True if an avatar file is present (Vite answers missing files with index.html). */
export async function avatarAvailable(url = AVATAR_URL): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'HEAD' })
    return res.ok && !(res.headers.get('content-type') ?? '').includes('text/html')
  } catch {
    return false
  }
}

/**
 * The 3D interviewer: three.js + TalkingHead with an Avaturn/Ready Player Me
 * style .glb (ARKit blendshapes + Oculus visemes).
 *
 * say() plays a sentence's audio through TalkingHead with lip-sync driven by
 * Kokoro's word timings, and fires the expression tags at the right moments.
 * It shares the page's AudioContext so the recorder can tap the voice.
 */
export class AvatarController implements Speaker {
  readonly head: TalkingHead
  private ctx: AudioContext
  private chain: Promise<void> = Promise.resolve()
  private generation = 0
  private nodTimer = 0
  private userSpeaking = false
  private running = true

  private constructor(head: TalkingHead, ctx: AudioContext) {
    this.head = head
    this.ctx = ctx
  }

  static async create(node: HTMLElement, ctx: AudioContext, body: 'F' | 'M', url = AVATAR_URL): Promise<AvatarController> {
    const head = new TalkingHead(node, {
      audioCtx: ctx,
      lipsyncModules: [], // loaded below: its dynamic import() doesn't survive bundling
      lipsyncLang: 'en',
      cameraView: 'head', // head and shoulders: the 'head' preset pulled back a little
      cameraDistance: 0.8,
      cameraY: 0.25,
      cameraRotateEnable: false,
      cameraPanEnable: false,
      cameraZoomEnable: false,
      avatarMood: 'neutral',
      avatarIdleEyeContact: 0.5,
      avatarIdleHeadMove: 0.4,
      avatarSpeakingEyeContact: 0.7,
      avatarSpeakingHeadMove: 0.5,
      lightAmbientIntensity: 2.2, // soft, even light
      lightDirectIntensity: 20,
      modelFPS: 30,
    })
    head.lipsync.en = new LipsyncEn()
    // Opaque "office wall" background, so recordings of the canvas aren't black.
    head.renderer.setClearColor(0xd5dbe2, 1)
    await head.showAvatar({
      url,
      body,
      avatarMood: 'neutral',
      lipsyncLang: 'en',
      // Avaturn T2 avatars: small head-angle and eyelid correction (TalkingHead's example config).
      baseline: { headRotateX: -0.05, eyeBlinkLeft: 0.15, eyeBlinkRight: 0.15 },
    })
    // [curious]: raised brows and a slight head tilt.
    head.animEmojis.curious = {
      dt: [400, 1600],
      rescale: [0, 1],
      vs: { browInnerUp: [0.6], browOuterUpLeft: [0.5], browOuterUpRight: [0.5], headRotateZ: [0.1], eyeWideLeft: [0.2], eyeWideRight: [0.2] },
    }
    const ctl = new AvatarController(head, ctx)
    if (import.meta.env.DEV) (window as unknown as { __avatar?: AvatarController }).__avatar = ctl // for debugging
    ctl.nodTimer = window.setInterval(() => ctl.maybeNod(), 3500)
    return ctl
  }

  /** The WebGL canvas (for recording the avatar). */
  get canvas(): HTMLCanvasElement {
    return this.head.renderer.domElement
  }

  /** The node carrying the avatar's voice (for the recorder). */
  get voiceOutput(): AudioNode {
    return this.head.audioReverbNode
  }

  /** Apply one expression tag (see SPEC.md). */
  express(tag: string) {
    const h = this.head
    try {
      switch (tag) {
        case 'neutral':
          h.setMood('neutral')
          break
        case 'smile':
          h.setMood('happy')
          break
        case 'thinking':
          h.setMood('neutral')
          h.playGesture('🤔', 1.6) // brief look up/away
          break
        case 'nod':
          h.playGesture('yes', 1.2)
          break
        case 'curious':
          h.playGesture('curious', 1.8)
          break
        case 'serious':
          h.setMood('neutral')
          h.makeEyeContact(3000)
          break
      }
    } catch (e) {
      console.warn('Avatar expression failed', tag, e)
    }
  }

  /** say(audio, words, timings, expressions): one sentence with lip-sync. */
  say(audio: AudioBuffer | null, words: WordTiming[], expressions: Expression[], text: string, onStart?: () => void) {
    const fire = expressions.map((e) => ({ fn: () => this.express(e.tag), at: expressionTime(text, words, e.char_index) }))
    if (!audio) {
      onStart?.()
      fire.forEach((f) => f.fn())
      return
    }
    this.head.speakAudio(
      {
        audio,
        words: words.map((w) => w.word),
        wtimes: words.map((w) => w.start_ms),
        wdurations: words.map((w) => Math.max(40, w.end_ms - w.start_ms)),
        markers: [() => onStart?.(), ...fire.map((f) => f.fn)],
        mtimes: [0, ...fire.map((f) => f.at)],
      },
      { lipsyncLang: 'en' },
    )
  }

  // ------------------------------------------------------------ Speaker -- //

  enqueue(sentence: SpokenSentence, onStart?: () => void) {
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
      this.say(buffer, sentence.words ?? [], sentence.expressions ?? [], sentence.text, onStart)
    })
  }

  private get busy() {
    return this.head.isSpeaking || this.head.isAudioPlaying || this.head.speechQueue.length > 0
  }

  async whenIdle(): Promise<void> {
    const gen = this.generation
    await this.chain
    await new Promise<void>((resolve) => {
      const check = () => {
        if (gen !== this.generation || !this.busy) resolve()
        else window.setTimeout(check, 60)
      }
      window.setTimeout(check, 60)
    })
  }

  pause() {
    this.running = false
    this.head.stop() // freezes the animation clock and suspends the audio: stays in sync
  }

  resume() {
    this.running = true
    this.head.start()
  }

  stop() {
    this.generation++
    this.chain = Promise.resolve()
    this.head.stopSpeaking()
  }

  /** While I talk: the avatar occasionally nods. */
  setUserSpeaking(on: boolean) {
    this.userSpeaking = on
  }

  private maybeNod() {
    if (this.running && this.userSpeaking && !this.busy && Math.random() < 0.45) this.head.playGesture('yes', 1)
  }

  destroy() {
    window.clearInterval(this.nodTimer)
    const canvas = this.canvas
    try {
      this.head.stop()
      this.head.dispose()
    } catch {
      /* already gone */
    }
    canvas?.remove()
  }
}

/** Time (ms) of the word where an expression's sentence starts. */
function expressionTime(text: string, words: WordTiming[], charIndex: number): number {
  if (!words.length || charIndex <= 0) return 0
  const before = text.slice(0, charIndex).split(/\s+/).filter((w) => /\w/.test(w)).length
  return words[Math.min(before, words.length - 1)].start_ms
}

interface AvatarProps {
  ctx: AudioContext
  body: 'F' | 'M'
  talking: boolean
  onReady: (avatar: AvatarController) => void
  onError: (message: string) => void
}

/** Mounts the 3D interviewer into the stage. */
export function Avatar({ ctx, body, talking, onReady, onError }: AvatarProps) {
  const node = useRef<HTMLDivElement>(null)
  const [progress, setProgress] = useState<string | null>('Loading interviewer…')

  useEffect(() => {
    let ctl: AvatarController | null = null
    let cancelled = false
    // Deferred one tick so React StrictMode's throwaway first mount never creates a scene.
    const timer = window.setTimeout(() => {
      AvatarController.create(node.current!, ctx, body)
        .then((c) => {
          if (cancelled) return c.destroy()
          ctl = c
          setProgress(null)
          onReady(c)
        })
        .catch((e: Error) => {
          if (!cancelled) {
            setProgress(null)
            onError(e.message)
          }
        })
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      ctl?.destroy()
    }
  }, [ctx, body])

  return (
    <div className={`avatar-frame ${talking ? 'talking' : ''}`}>
      <div ref={node} className="avatar-canvas" />
      {progress && <div className="avatar-progress muted small">{progress}</div>}
    </div>
  )
}
