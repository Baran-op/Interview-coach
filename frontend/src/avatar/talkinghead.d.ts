// Minimal typings for the parts of TalkingHead (MIT, met4citizen) we use.
declare module '@met4citizen/talkinghead' {
  export interface SpeakAudioInput {
    audio?: AudioBuffer
    words?: string[]
    wtimes?: number[]
    wdurations?: number[]
    markers?: (() => void)[]
    mtimes?: number[]
  }
  export class TalkingHead {
    constructor(node: HTMLElement, opt?: Record<string, unknown>)
    showAvatar(avatar: Record<string, unknown>, onprogress?: ((e: ProgressEvent) => void) | null): Promise<void>
    speakAudio(r: SpeakAudioInput, opt?: { lipsyncLang?: string } | null): void
    stopSpeaking(): void
    setMood(mood: string): void
    playGesture(name: string, dur?: number, mirror?: boolean, ms?: number): void
    makeEyeContact(ms: number): void
    lookAhead(ms: number): void
    lookAtCamera(ms: number): void
    start(): void
    stop(): void
    dispose(): void
    lipsync: Record<string, unknown>
    animEmojis: Record<string, unknown>
    isSpeaking: boolean
    isAudioPlaying: boolean
    speechQueue: unknown[]
    renderer: { domElement: HTMLCanvasElement; setClearColor(color: number, alpha?: number): void }
    audioReverbNode: AudioNode
  }
}

declare module '@met4citizen/talkinghead/modules/lipsync-en.mjs' {
  export class LipsyncEn {}
}
