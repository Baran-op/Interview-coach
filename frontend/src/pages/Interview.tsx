import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { api, type Expression, type Health, type InterviewEvent, type Pack } from '../api'
import { InterviewerPlayer, type SpokenSentence } from '../audio/player'
import { TurnListener } from '../audio/vad'
import { encodeWav } from '../audio/wav'

type Phase =
  | 'starting' // opening the session
  | 'thinking' // waiting for the interviewer's reply
  | 'speaking' // interviewer audio playing
  | 'listening' // my turn
  | 'finished' // interviewer said [END]
  | 'ended'

interface Message {
  id: number
  speaker: 'interviewer' | 'candidate'
  text: string
  expressions?: Expression[]
  pending?: boolean
}

interface Latency {
  replyMs: number // turn end detected -> first interviewer audio
  sttMs: number | null
  silenceMs: number
}

interface Props {
  pack: Pack
  onExit: () => void
}

const SILENCE_OPTIONS = [1500, 2000, 2500, 3000]

function readSilence(): number {
  try {
    const v = Number(localStorage.getItem('silenceMs'))
    return SILENCE_OPTIONS.includes(v) ? v : 2000
  } catch {
    return 2000
  }
}

function formatTime(ms: number) {
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable)
}

export default function Interview({ pack, onExit }: Props) {
  const interviewer = pack.options.interviewer_name || 'Interviewer'

  const [phase, setPhaseState] = useState<Phase>('starting')
  const [paused, setPaused] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [caption, setCaption] = useState('')
  const [micSpeaking, setMicSpeaking] = useState(false)
  const [pushToTalk, setPushToTalk] = useState(false)
  const [voiceMode, setVoiceMode] = useState(false)
  const [voiceNote, setVoiceNote] = useState<string | null>('Checking voice models…')
  const [needsUnlock, setNeedsUnlock] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [latency, setLatency] = useState<Latency | null>(null)
  const [silenceMs, setSilenceMs] = useState(readSilence)
  const [draft, setDraft] = useState('')
  const [elapsed, setElapsed] = useState(0)

  const phaseRef = useRef<Phase>('starting')
  const pausedRef = useRef(false)
  const sessionRef = useRef<string | null>(null)
  const playerRef = useRef<InterviewerPlayer | null>(null)
  const listenerRef = useRef<TurnListener | null>(null)
  const voiceRef = useRef(false)
  const lastSentences = useRef<SpokenSentence[]>([])
  const nextId = useRef(1)
  const started = useRef(false)
  const mounted = useRef(false)
  const clock = useRef({ startedAt: 0, pausedAt: 0, pausedTotal: 0 })
  const bottom = useRef<HTMLDivElement>(null)
  const silenceRef = useRef(silenceMs)

  const setPhase = (p: Phase) => {
    phaseRef.current = p
    setPhaseState(p)
  }

  // ------------------------------------------------------------ helpers -- //

  const addMessage = (m: Omit<Message, 'id'>) => {
    const id = nextId.current++
    setMessages((ms) => [...ms, { ...m, id }])
    return id
  }
  const patchMessage = (id: number, patch: (m: Message) => Partial<Message>) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)))
  const dropMessage = (id: number) => setMessages((ms) => ms.filter((m) => m.id !== id))

  const endSession = useCallback(async () => {
    const id = sessionRef.current
    if (phaseRef.current === 'ended') return
    setPhase('ended')
    playerRef.current?.stop()
    await listenerRef.current?.cancel().catch(() => {})
    setMicSpeaking(false)
    if (id) {
      try {
        await api.endSession(id)
      } catch (e) {
        setError((e as Error).message)
      }
    }
  }, [])

  const startListening = async () => {
    if (phaseRef.current === 'ended' || phaseRef.current === 'finished') return
    setPhase('listening')
    if (voiceRef.current && listenerRef.current) {
      try {
        await listenerRef.current.listen()
      } catch (e) {
        voiceRef.current = false
        setVoiceMode(false)
        setVoiceNote(`Microphone unavailable (${(e as Error).message}). Type your answers instead.`)
      }
    }
  }

  /** Play an interviewer reply as it streams in, then hand the turn back to me. */
  const runReply = async (
    stream: AsyncGenerator<InterviewEvent>,
    opts: { candidateMsg?: number; turnEndedAt?: number; silenceMs?: number } = {},
  ) => {
    const player = playerRef.current!
    let replyMsg: number | null = null
    let isFinal = false
    let sttMs: number | null = null
    const sentences: SpokenSentence[] = []
    setPhase('thinking')
    try {
      for await (const ev of stream) {
        if (phaseRef.current === 'ended') return
        if (ev.type === 'session') {
          sessionRef.current = ev.session_id
          clock.current.startedAt = performance.now()
        } else if (ev.type === 'transcript') {
          sttMs = ev.stt_ms
          if (opts.candidateMsg) patchMessage(opts.candidateMsg, () => ({ text: ev.text, pending: false }))
        } else if (ev.type === 'sentence') {
          const s = { text: ev.text, audioBase64: ev.audio_wav_base64 }
          sentences.push(s)
          if (replyMsg === null) {
            replyMsg = addMessage({ speaker: 'interviewer', text: ev.text, expressions: ev.expressions })
          } else {
            patchMessage(replyMsg, (m) => ({
              text: `${m.text} ${ev.text}`,
              expressions: [
                ...(m.expressions ?? []),
                ...ev.expressions.map((x) => ({ ...x, char_index: x.char_index + m.text.length + 1 })),
              ],
            }))
          }
          if (ev.tts_error) console.warn('TTS error:', ev.tts_error)
          const first = ev.index === 0
          player.enqueue(s, () => {
            setCaption(ev.text)
            if (phaseRef.current === 'thinking') setPhase('speaking')
            if (first && opts.turnEndedAt) {
              setLatency({ replyMs: performance.now() - opts.turnEndedAt, sttMs, silenceMs: opts.silenceMs ?? 0 })
            }
          })
        } else if (ev.type === 'done') {
          isFinal = ev.is_final
          if (replyMsg !== null) patchMessage(replyMsg, () => ({ text: ev.reply_text, expressions: ev.expressions }))
        } else if (ev.type === 'error') {
          throw new Error(ev.message)
        }
      }
    } catch (e) {
      const err = e as Error & { status?: number }
      if (opts.candidateMsg && err.status === 422) {
        dropMessage(opts.candidateMsg)
        setNotice(err.message)
      } else {
        setError(err.message)
      }
      await player.whenIdle()
      if (sessionRef.current) await startListening()
      return
    }
    if (sentences.length) lastSentences.current = sentences
    await player.whenIdle()
    if (phaseRef.current === 'ended') return
    if (isFinal) {
      setPhase('finished')
      await endSession()
    } else {
      await startListening()
    }
  }

  // ---------------------------------------------------------- my turns -- //

  const submitAudio = (audio: Float32Array, bySilence: boolean) => {
    const id = sessionRef.current
    if (!id) return
    const turnEndedAt = performance.now()
    setMicSpeaking(false)
    setNotice(null)
    setError(null)
    const candidateMsg = addMessage({ speaker: 'candidate', text: '…', pending: true })
    const silenceMs = bySilence ? silenceRef.current : 0
    void runReply(api.sendAudio(id, encodeWav(audio)), { candidateMsg, turnEndedAt, silenceMs })
  }

  const submitText = async () => {
    const text = draft.trim()
    const id = sessionRef.current
    if (!text || !id || phaseRef.current !== 'listening') return
    setDraft('')
    setNotice(null)
    setError(null)
    if (listenerRef.current?.listening) await listenerRef.current.cancel()
    const candidateMsg = addMessage({ speaker: 'candidate', text })
    void runReply(api.sendText(id, text), { candidateMsg })
  }

  // ------------------------------------------------------------- setup -- //

  const teardown = useCallback(() => {
    if (sessionRef.current && phaseRef.current !== 'ended') void api.endSession(sessionRef.current).catch(() => {})
    phaseRef.current = 'ended'
    void listenerRef.current?.destroy()
    playerRef.current?.destroy()
    listenerRef.current = null
    playerRef.current = null
  }, [])

  useEffect(() => {
    mounted.current = true
    if (!started.current) {
      started.current = true
      void (async () => {
        const player = new InterviewerPlayer()
        playerRef.current = player
        if (!(await player.unlock())) setNeedsUnlock(true)

        // Voice needs both models loaded on the backend and a working mic + VAD.
        let health: Health | null = null
        try {
          health = await api.health()
        } catch {
          /* handled below */
        }
        if (health?.voice_ready) {
          const listener = new TurnListener(
            {
              onTurn: submitAudio,
              onEmpty: () => {
                setNotice("I didn't hear anything. Try again.")
                void startListening()
              },
              onSpeechStart: () => setMicSpeaking(true),
              onSpeechEnd: () => setMicSpeaking(false),
            },
            silenceRef.current,
          )
          try {
            await listener.init()
            listenerRef.current = listener
            voiceRef.current = true
            setVoiceMode(true)
            setVoiceNote(null)
          } catch (e) {
            setVoiceNote(`Voice activity detection failed to load (${(e as Error).message}). Type your answers instead.`)
          }
        } else if (health) {
          const why = [health.whisper, health.kokoro]
            .filter((m) => m.status !== 'loaded')
            .map((m) => `${m.model.split('/').pop()}: ${m.status}${m.error ? ` (${m.error})` : ''}`)
            .join('; ')
          setVoiceNote(`Voice is off for this session: ${why}. Type your answers instead.`)
        } else {
          setVoiceNote('Backend not reachable.')
        }

        await runReply(api.startSession(pack.id))
      })().catch((e: Error) => setError(e.message))
    }
    return () => {
      mounted.current = false
      // StrictMode mounts twice in dev: only tear down if we really unmounted.
      window.setTimeout(() => {
        if (!mounted.current) teardown()
      }, 0)
    }
  }, [pack.id])

  // Timer (stops while paused or after the end).
  useEffect(() => {
    const t = window.setInterval(() => {
      const c = clock.current
      if (!c.startedAt || phaseRef.current === 'ended') return
      const now = pausedRef.current ? c.pausedAt : performance.now()
      setElapsed(now - c.startedAt - c.pausedTotal)
    }, 500)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ---------------------------------------------------------- controls -- //

  const done = () => {
    if (phaseRef.current === 'listening' && listenerRef.current?.listening) void listenerRef.current.finish()
  }

  const togglePause = async () => {
    const player = playerRef.current
    const listener = listenerRef.current
    if (!pausedRef.current) {
      pausedRef.current = true
      setPaused(true)
      clock.current.pausedAt = performance.now()
      player?.pause()
      if (listener?.listening) await listener.suspend()
    } else {
      pausedRef.current = false
      setPaused(false)
      clock.current.pausedTotal += performance.now() - clock.current.pausedAt
      player?.resume()
      if (phaseRef.current === 'listening' && voiceRef.current) await listener?.resume()
    }
  }

  const repeatQuestion = async () => {
    const player = playerRef.current
    const listener = listenerRef.current
    if (!player || phaseRef.current !== 'listening' || pausedRef.current || !lastSentences.current.length) return
    const wasListening = !!listener?.listening
    if (wasListening) await listener!.suspend()
    setPhase('speaking')
    for (const s of lastSentences.current) player.enqueue(s, () => setCaption(s.text))
    await player.whenIdle()
    if ((phaseRef.current as Phase) !== 'speaking') return // ended meanwhile
    setPhase('listening')
    if (wasListening) await listener!.resume()
  }

  const changeSilence = (ms: number) => {
    setSilenceMs(ms)
    silenceRef.current = ms
    listenerRef.current?.setSilenceMs(ms)
    try {
      localStorage.setItem('silenceMs', String(ms))
    } catch {
      /* not persisted */
    }
  }

  const unlockAudio = async () => {
    if (await playerRef.current?.unlock()) setNeedsUnlock(false)
  }

  // Spacebar push-to-talk: hold to keep talking through pauses, release to send.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || isTyping(e.target)) return
      if (phaseRef.current !== 'listening' || !listenerRef.current?.listening || pausedRef.current) return
      e.preventDefault()
      listenerRef.current.hold(true)
      setPushToTalk(true)
    }
    const up = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || isTyping(e.target)) return
      if (!listenerRef.current) return
      e.preventDefault()
      setPushToTalk((held) => {
        if (held) void listenerRef.current?.finish()
        return false
      })
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  const onComposerKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void submitText()
    }
  }

  // ------------------------------------------------------------ render -- //

  const status = paused
    ? 'Paused'
    : {
        starting: 'Connecting…',
        thinking: `${interviewer} is thinking…`,
        speaking: `${interviewer} is speaking`,
        listening: voiceMode
          ? pushToTalk
            ? 'Push-to-talk: release Space to send'
            : micSpeaking
              ? 'Listening… (pause to finish)'
              : 'Your turn: answer out loud'
          : 'Your turn: type your answer',
        finished: 'Interview finished',
        ended: 'Interview ended',
      }[phase]

  const live = phase !== 'ended' && phase !== 'finished'
  const myTurn = phase === 'listening' && !paused

  return (
    <div className="interview card">
      <div className="interview-bar">
        <span>
          {pack.role || pack.title}
          {pack.company ? ` · ${pack.company}` : ''}
        </span>
        <span className="timer">{formatTime(elapsed)}</span>
        {live ? (
          <button className="danger" onClick={() => void endSession()} disabled={!sessionRef.current}>
            End interview
          </button>
        ) : (
          <button onClick={onExit}>Back to setup</button>
        )}
      </div>

      {voiceNote && <div className="banner">{voiceNote}</div>}
      {needsUnlock && (
        <div className="banner">
          Your browser blocked sound. <button onClick={() => void unlockAudio()}>Enable sound</button>
        </div>
      )}

      <div className="interview-body">
        <section className="stage">
          <div className={`stage-face ${phase === 'speaking' && !paused ? 'talking' : ''}`} aria-hidden>
            {interviewer.slice(0, 1).toUpperCase()}
          </div>
          <div className="caption" aria-live="polite">
            {caption || (phase === 'starting' ? '…' : '')}
          </div>
          <div className={`status ${myTurn && voiceMode ? (micSpeaking || pushToTalk ? 'hot' : 'armed') : ''}`}>
            <span className="dot" /> {status}
          </div>
          <div className="controls">
            {voiceMode && (
              <button className="primary" onClick={done} disabled={!myTurn}>
                Done
              </button>
            )}
            <button onClick={() => void togglePause()} disabled={!live || phase === 'starting'}>
              {paused ? 'Resume' : 'Pause'}
            </button>
            <button onClick={() => void repeatQuestion()} disabled={!myTurn || !lastSentences.current.length}>
              Repeat question
            </button>
          </div>
          {voiceMode && (
            <div className="muted small hint">
              Your turn ends after{' '}
              <select value={silenceMs} onChange={(e) => changeSilence(Number(e.target.value))}>
                {SILENCE_OPTIONS.map((ms) => (
                  <option key={ms} value={ms}>
                    {ms / 1000} s
                  </option>
                ))}
              </select>{' '}
              of silence, or press Done. Hold Space to keep talking through pauses.
            </div>
          )}
          {latency && (
            <div className="muted small" title="Time from the end of your answer to the interviewer's voice">
              Last reply: {((latency.silenceMs + latency.replyMs) / 1000).toFixed(1)} s after you stopped talking (
              {latency.silenceMs ? `${(latency.silenceMs / 1000).toFixed(1)} s silence + ` : ''}
              {(latency.replyMs / 1000).toFixed(1)} s processing
              {latency.sttMs != null ? `, of which ${(latency.sttMs / 1000).toFixed(1)} s transcription` : ''})
            </div>
          )}
        </section>

        <section className="transcript">
          <div className="chat">
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.speaker} ${m.pending ? 'pending' : ''}`}>
                <div className="who">{m.speaker === 'interviewer' ? interviewer : 'You'}</div>
                <div className="bubble">{m.text}</div>
                {m.expressions && m.expressions.length > 0 && (
                  <div className="tags">
                    {m.expressions.map((x, j) => (
                      <span key={j} className="tag" title={`at char ${x.char_index}`}>
                        {x.tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {phase === 'ended' && <div className="banner">Interview ended. Feedback reports arrive in Milestone 3.</div>}
            <div ref={bottom} />
          </div>
          {notice && <div className="banner">{notice}</div>}
          {error && <div className="banner error">{error}</div>}
          <div className="composer">
            <textarea
              rows={voiceMode ? 2 : 4}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onComposerKey}
              placeholder={!live ? 'Interview finished' : voiceMode ? 'Or type an answer (Ctrl/⌘+Enter)' : 'Type your answer… (Ctrl/⌘+Enter to send)'}
              disabled={!myTurn}
            />
            <button onClick={() => void submitText()} disabled={!myTurn || !draft.trim()}>
              Send
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
