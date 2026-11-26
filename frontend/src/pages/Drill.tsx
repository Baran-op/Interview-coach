import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, categoryLabel, criteriaHash, reportCriteria, FACE_FLAG_LABEL, FACE_MOMENT_LABEL, VOICE_FLAG_LABEL, faceTooltip, voiceTooltip, type FaceMoment, type DrillAttempt, type DrillQuestion, type Pack } from '../api'
import { InterviewerPlayer, type Speaker } from '../audio/player'
import { TurnListener, type SpeechSegment } from '../audio/vad'
import { encodeWav } from '../audio/wav'
import { Avatar, AvatarController, avatarAvailable } from '../avatar/Avatar'
import { FaceTracker, faceModelAvailable, getFaceTracking } from '../face/FaceTracker'
import { Chevron } from '../components/Dropdown'
import { parseFrom } from '../voice/answers'
import LastTime, { type LastInfo } from '../voice/LastTime'
import TurnVoice from '../voice/TurnVoice'
import PackHeader from '../components/PackHeader'

interface Current {
  key: string
  question: string
  category: string | null
}

/** Same normalisation as backend/drill.py question_key(). */
async function questionKey(question: string): Promise<string> {
  const norm = question
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
  const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(norm))
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 12)
}

const clock = (ms: number) => `${Math.floor(Math.round(ms / 1000) / 60)}:${String(Math.round(ms / 1000) % 60).padStart(2, '0')}`

/** Moments in a drill answer: time into the answer and what you were saying; no play button, as Drill records no video. */
const momentText = (m: FaceMoment) =>
  `${FACE_MOMENT_LABEL[m.kind]} ${clock(m.start_ms)}\u2013${clock(m.end_ms)} (${Math.max(0, Math.round((m.end_ms - m.start_ms) / 1000))} s)`

function fmt(n: number | null) {
  return n == null ? '–' : n.toFixed(1)
}

function delta(d: number) {
  const r = Math.round(d * 10) / 10
  return r > 0 ? `+${r.toFixed(1)}` : r < 0 ? r.toFixed(1) : '±0'
}

interface Props {
  packId: string
  initialQuestion: string | null
  /** `<session>~<turn>~<section>` from a Review "Try again in Drill" link. */
  from?: string | null
  onStart: (pack: Pack) => void
}

/** "Pitch range 3.1 → 5.0 st (usual 5.4) · flat stretches 2 → 0": behaviour only, no verdict words. */
function voiceComparison(old: LastInfo, now: DrillAttempt['result']): string | null {
  const v = now?.delivery?.voice
  if (old.pitchRange == null || v?.pitch_range_st == null) return null
  const bits = [`Pitch range ${old.pitchRange.toFixed(1)} \u2192 ${v.pitch_range_st.toFixed(1)} st` + (old.usual != null ? ` (usual ${old.usual.toFixed(1)})` : '')]
  if (old.sections != null && v.sections) bits.push(`flat stretches ${old.sections} \u2192 ${v.sections.length}`)
  return bits.join(' \u00b7 ')
}

export default function Drill({ packId, initialQuestion, from = null, onStart }: Props) {
  const fromRef = useMemo(() => parseFrom(from), [from])
  const [fromActive, setFromActive] = useState(false)
  const [last, setLast] = useState<LastInfo | null>(null)
  const [pack, setPack] = useState<Pack | null>(null)
  const [questions, setQuestions] = useState<DrillQuestion[]>([])
  const [labels, setLabels] = useState<Record<string, string>>({}) // the brief's category labels
  const [current, setCurrent] = useState<Current | null>(null)
  const [attempts, setAttempts] = useState<DrillAttempt[]>([])
  const [result, setResult] = useState<{ attempt: DrillAttempt; previous: DrillAttempt | null } | null>(null)
  const [custom, setCustom] = useState('')
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [phase, setPhase] = useState<'idle' | 'speaking' | 'listening' | 'scoring'>('idle')
  const [voiceReady, setVoiceReady] = useState(false)
  const [avatarCtx, setAvatarCtx] = useState<AudioContext | null>(null)
  const [camStream, setCamStream] = useState<MediaStream | null>(null)
  const selfView = useRef<HTMLVideoElement>(null)
  const faceRef = useRef<FaceTracker | null>(null)
  const originRef = useRef(performance.now()) // face and speech times count from here (the start of the answer)
  const clockNow = () => performance.now() - originRef.current

  const playerRef = useRef<InterviewerPlayer | null>(null)
  const avatarRef = useRef<AvatarController | null>(null)
  const listenerRef = useRef<TurnListener | null>(null)
  const currentRef = useRef<Current | null>(null)
  currentRef.current = current

  const player = () => (playerRef.current ??= new InterviewerPlayer())
  const speaker = (): Speaker => avatarRef.current ?? player()

  const refreshQuestions = useCallback(async () => {
    const q = await api.drillQuestions(packId)
    setQuestions(q.questions)
    setLabels(q.labels ?? {})
  }, [packId])

  const select = useCallback(
    async (question: string, category: string | null, key?: string) => {
      speaker().stop()
      void listenerRef.current?.cancel()
      setPhase('idle')
      setResult(null)
      setTyped('')
      setError(null)
      setNotice(null)
      const k = key ?? (await questionKey(question))
      setCurrent({ key: k, question, category })
      try {
        setAttempts((await api.drillAttempts(packId, k)).attempts)
      } catch (e) {
        setError((e as Error).message)
      }
    },
    [packId], // eslint-disable-line react-hooks/exhaustive-deps
  )

  // Load the pack and question list, then open the ?q= question if there is one.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [p, q] = await Promise.all([api.getPack(packId), api.drillQuestions(packId)])
        if (cancelled) return
        setPack(p)
        setQuestions(q.questions)
        setLabels(q.labels ?? {})
        if (initialQuestion) {
          const key = await questionKey(initialQuestion)
          const known = q.questions.find((x) => x.key === key)
          await select(known?.question ?? initialQuestion, known?.category ?? null, key)
          if (!cancelled) setFromActive(true)
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [packId, initialQuestion, select])

  // Voice and the avatar are optional extras; typing always works.
  useEffect(() => {
    let cancelled = false
    void api
      .health()
      .then((h) => !cancelled && setVoiceReady(h.voice_ready))
      .catch(() => {})
    void avatarAvailable().then((ok) => {
      if (ok && !cancelled) setAvatarCtx(player().ctx)
    })
    return () => {
      cancelled = true
      avatarRef.current = null
      void listenerRef.current?.destroy()
      playerRef.current?.destroy()
      playerRef.current = null
    }
  }, [])

  // The camera opens only when the Setup toggle is on and the model exists, and is released on leaving the page.
  useEffect(() => {
    let cancelled = false
    let stream: MediaStream | null = null
    void (async () => {
      if (!getFaceTracking() || !(await faceModelAvailable())) return
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false })
      } catch (e) {
        if (!cancelled) setNotice(`Camera not available (${(e as Error).name === 'NotAllowedError' ? 'permission denied' : (e as Error).message}). Drilling without face stats.`)
        return
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop())
        return
      }
      const tracker = await FaceTracker.create(stream, clockNow)
      if (cancelled) {
        tracker?.stop()
        stream.getTracks().forEach((t) => t.stop())
        return
      }
      if (!tracker) {
        stream.getTracks().forEach((t) => t.stop())
        setNotice('Face tracking could not start. Drilling without face stats.')
        return
      }
      faceRef.current = tracker
      setCamStream(stream)
    })()
    return () => {
      cancelled = true
      faceRef.current?.stop()
      faceRef.current = null
      stream?.getTracks().forEach((t) => t.stop())
    }
  }, [])

  useEffect(() => {
    if (selfView.current) selfView.current.srcObject = camStream
  }, [camStream, current])

  const playQuestion = async () => {
    if (!current || !pack) return
    setError(null)
    await player().unlock()
    setPhase('speaking')
    faceRef.current?.startSegment('listen') // you look at the screen while the question is read: calibrates "on screen"
    try {
      const { sentences } = await api.tts(current.question, pack.options.voice)
      if (!sentences.some((s) => s.audio_wav_base64)) setNotice('No voice available (Kokoro is not ready). Read the question above.')
      for (const s of sentences) {
        speaker().enqueue({ text: s.text, audioBase64: s.audio_wav_base64, words: s.word_timings, expressions: s.expressions })
      }
      await speaker().whenIdle()
    } catch (e) {
      setError((e as Error).message)
    }
    faceRef.current?.endSegment()
    setPhase((p) => (p === 'speaking' ? 'idle' : p))
  }

  const submit = async (a: { text?: string; wav?: Blob; seconds?: number; segments?: SpeechSegment[] }) => {
    const cur = currentRef.current
    if (!cur) return
    setPhase('scoring')
    setError(null)
    try {
      const face = a.wav ? (faceRef.current?.endSegment() ?? null) : null
      const r = await api.drillAttempt(packId, { question: cur.question, category: cur.category, ...a, face })
      setResult(r)
      setTyped('')
      setAttempts((await api.drillAttempts(packId, cur.key)).attempts)
      await refreshQuestions()
    } catch (e) {
      setError((e as Error).message)
    }
    setPhase('idle')
  }

  const startListening = async () => {
    if (!current) return
    speaker().stop()
    setError(null)
    setResult(null)
    try {
      if (!listenerRef.current) {
        const l = new TurnListener(
          {
            onTurn: (audio, _bySilence, segments) => void submit({ wav: encodeWav(audio), seconds: audio.length / 16000, segments }),
            onEmpty: () => {
              faceRef.current?.endSegment()
              setNotice("I didn't hear anything. Try again.")
              setPhase('idle')
            },
          },
          0, // Done-only: thinking pauses are normal in a drill
          clockNow,
        )
        await l.init()
        listenerRef.current = l
      }
      setNotice(null)
      setPhase('listening')
      originRef.current = performance.now()
      faceRef.current?.endSegment()
      faceRef.current?.startSegment('answer')
      await listenerRef.current.listen()
    } catch (e) {
      faceRef.current?.endSegment()
      setPhase('idle')
      setError(`Could not start the microphone: ${(e as Error).message}`)
    }
  }

  const done = () => {
    setPhase('scoring')
    void listenerRef.current?.finish()
  }

  const busy = phase === 'scoring'

  return (
    <div className="drill">
      {/* "Answer by voice" is this page's main action, so Start is a secondary button here. */}
      <PackHeader packId={packId} tab="drill" onStart={onStart} primary={false} />
      <p className="muted lede drill-lede">Practise one question at a time. Each attempt you submit uses one Claude request.</p>
      {error && <div className="banner error">{error}</div>}
      <div className="drill-body">
        <aside className="card drill-list">
          <h2>Questions</h2>
          {questions.map((q) => (
            <button
              key={q.key}
              className={`drill-q ${current?.key === q.key ? 'on' : ''}`}
              onClick={() => {
                setFromActive(false)
                void select(q.question, q.category, q.key)
              }}
            >
              <span>{q.question}</span>
              <span className="drill-chips">
                {q.source === 'report' && <span className="chip">weak</span>}
                {q.attempts > 0 && (
                  <span className="chip" title="best and latest average">
                    best {fmt(q.best)} · latest {fmt(q.latest)}
                  </span>
                )}
              </span>
            </button>
          ))}
          <form
            className="drill-custom"
            onSubmit={(e) => {
              e.preventDefault()
              if (custom.trim()) {
                setFromActive(false)
                void select(custom.trim(), null)
                setCustom('')
              }
            }}
          >
            <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Your own question" aria-label="Your own question" />
            <button type="submit" disabled={!custom.trim()}>
              Practise
            </button>
          </form>
        </aside>

        <section className="card drill-main">
          {!current ? (
            <p className="muted">Pick a question to practise.</p>
          ) : (
            <>
              {camStream && (
                <figure className="drill-self">
                  <video ref={selfView} className="self-view-inline" autoPlay muted playsInline />
                  <figcaption className="muted small">Camera on for eye contact stats; nothing is recorded. Turn it off in Setup.</figcaption>
                </figure>
              )}
              {avatarCtx && (
                <Avatar
                  ctx={avatarCtx}
                  body={pack?.options.voice?.[1] === 'm' ? 'M' : 'F'}
                  talking={phase === 'speaking'}
                  onReady={(a) => (avatarRef.current = a)}
                  onError={() => {
                    avatarRef.current = null
                    setAvatarCtx(null)
                  }}
                />
              )}
              <h2>{current.question}</h2>
              {current.category && <span className="chip">{labels[current.category] ?? categoryLabel(current.category)}</span>}
              <div className="actions">
                <button onClick={() => void playQuestion()} disabled={phase !== 'idle'}>
                  {phase === 'speaking' ? 'Speaking…' : 'Hear the question'}
                </button>
                {voiceReady &&
                  (phase === 'listening' ? (
                    <button className="primary" onClick={done}>
                      Done
                    </button>
                  ) : (
                    <button className="primary" onClick={() => void startListening()} disabled={phase !== 'idle'}>
                      Answer by voice
                    </button>
                  ))}
              </div>
              {fromActive && fromRef && <LastTime from={fromRef} onInfo={setLast} />}
              {phase === 'listening' && <p className="muted small">Listening. Pauses never end it; press Done when finished.</p>}
              {notice && <div className="banner">{notice}</div>}
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (typed.trim()) void submit({ text: typed.trim() })
                }}
              >
                <textarea
                  rows={4}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="Or type your answer"
                  disabled={phase === 'scoring' || phase === 'listening'}
                />
                <div className="actions">
                  <button type="submit" disabled={phase !== 'idle' || !typed.trim()}>
                    Score my answer
                  </button>
                  <span className="muted small">Each attempt (typed or spoken) uses one Claude request.</span>
                </div>
              </form>
              {busy && <p className="muted">Scoring…</p>}

              {result?.attempt.result && (
                <div className="drill-result">
                  <h3>
                    Score {fmt(result.attempt.result.average)}
                    {result.previous?.result && criteriaHash(result.previous.result) === criteriaHash(result.attempt.result) && (
                      <span className="chip">{delta(result.attempt.result.average - result.previous.result.average)} since last time</span>
                    )}
                  </h3>
                  <LengthLine d={result.attempt.result.delivery} />
                  {fromActive && last && voiceComparison(last, result.attempt.result) && <p className="small">{voiceComparison(last, result.attempt.result)}</p>}
                  <div className="bars">
                    {reportCriteria(result.attempt.result).map((c) => (
                      <Bar key={c.key} label={c.name} value={result.attempt.result!.scores[c.key] ?? 0} />
                    ))}
                  </div>
                  {(result.attempt.result.delivery?.voice_flags?.length ?? 0) > 0 && (
                    <p className="small" title={voiceTooltip(result.attempt.result.delivery!) || undefined}>
                      Voice:{' '}
                      {result.attempt.result.delivery!.voice_flags!.map((f, i) => (
                        <span key={f}>
                          {i > 0 && ', '}
                          <span className="out-of-target">{VOICE_FLAG_LABEL[f]}</span>
                        </span>
                      ))}
                    </p>
                  )}
                  {result.attempt.has_audio && (
                    <DrillVoice key={result.attempt.id} packId={packId} attemptId={result.attempt.id} from={fromActive ? fromRef : null} />
                  )}
                  {result.attempt.result.delivery?.face && (
                    <div className="small" title={faceTooltip(result.attempt.result.delivery) || undefined}>
                      <p>
                        {result.attempt.result.delivery.face.on_screen_pct != null ? `Eye contact ${Math.round(result.attempt.result.delivery.face.on_screen_pct)}%` : 'Face not found often enough to measure'}
                        {(result.attempt.result.delivery.face_flags?.length ?? 0) > 0 && ': '}
                        {result.attempt.result.delivery.face_flags?.map((f, i) => (
                          <span key={f}>
                            {i > 0 && ', '}
                            <span className="out-of-target">{FACE_FLAG_LABEL[f]}</span>
                          </span>
                        ))}
                      </p>
                      {(result.attempt.result.delivery.face.moments?.length ?? 0) > 0 && (
                        <ul>
                          {result.attempt.result.delivery.face.moments!.map((m, i) => (
                            <li key={i}>
                              {momentText(m)}
                              {m.quote && (
                                <>
                                  , while saying: <em>{'\u201c'}{m.quote}{'\u201d'}</em>
                                </>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                  {result.previous && result.attempt.result.improved.length > 0 && (
                    <>
                      <strong>Better than last time</strong>
                      <ul className="small">
                        {result.attempt.result.improved.map((t, i) => (
                          <li key={i}>{t}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {result.attempt.result.tips.length > 0 && (
                    <>
                      <strong>To improve</strong>
                      <ul className="small">
                        {result.attempt.result.tips.map((t, i) => (
                          <li key={i}>{t}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {result.attempt.result.better_answer && (
                    <details className="better">
                      <summary>Show a stronger answer</summary>
                      <p>{result.attempt.result.better_answer}</p>
                    </details>
                  )}
                  <p className="muted small">Answer it again to see what changes.</p>
                </div>
              )}

              {attempts.length > 0 && (
                <div className="drill-history">
                  <h3>Attempts</h3>
                  <table className="small">
                    <tbody>
                      {attempts.map((a, i) => {
                        // Only attempts scored with the latest attempt's criteria are compared.
                        const latestHash = criteriaHash(attempts[attempts.length - 1].result)
                        const comparable = criteriaHash(a.result) === latestHash
                        const avg = a.result?.average ?? null
                        const before = attempts.slice(0, i).filter((b) => criteriaHash(b.result) === latestHash)
                        const prev = comparable && before.length ? (before[before.length - 1].result?.average ?? null) : null
                        return (
                          <tr key={a.id} className={comparable ? '' : 'earlier'}>
                            <td>{i + 1}</td>
                            <td>{new Date(a.created_at).toLocaleString()}</td>
                            <td>{fmt(avg)}</td>
                            <td>{!comparable ? 'earlier criteria' : avg != null && prev != null ? delta(avg - prev) : ''}</td>
                            <td title={voiceTooltip(a.result?.delivery ?? {}) || undefined}>
                              {a.result?.delivery?.voice?.pitch_range_st != null ? `${a.result.delivery.voice.pitch_range_st.toFixed(1)} st` : ''}
                            </td>
                            <td title={faceTooltip(a.result?.delivery ?? {}) || undefined}>
                              {a.result?.delivery?.face?.on_screen_pct != null ? `eye contact ${Math.round(a.result.delivery.face.on_screen_pct)}%` : ''}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  )
}

/** "1:12 (aim 1:00-1:30), too long" from the attempt's length and its category's target. */
function LengthLine({ d }: { d?: Record<string, unknown> & { seconds?: number | null } }) {
  const target = d?.target as [number, number] | null | undefined
  if (!d?.seconds || !target) return null
  const mmss = (s: number) => clock(s * 1000)
  return (
    <p className="small delivery-line">
      Length <span className={d.flag ? 'out-of-target' : ''}>{mmss(d.seconds)}</span> (aim {mmss(target[0])}-{mmss(target[1])})
      {d.flag === 'short' ? ', on the short side' : d.flag === 'long' ? ', on the long side' : ''}
    </p>
  )
}

function Bar({ label, value }: { label: string; value: number }) {
  return (
    <>
      <span className="muted">{label}</span>
      <span className="bar" role="meter" aria-valuemin={1} aria-valuemax={5} aria-valuenow={value} aria-label={label}>
        <span style={{ width: `${(value / 5) * 100}%` }} />
      </span>
      <span>{value}</span>
    </>
  )
}

/** The attempt's pitch graph (and, with a `from` link, the interview answer on the same scale). Loads only when opened. */
function DrillVoice({ packId, attemptId, from }: { packId: string; attemptId: string; from: ReturnType<typeof parseFrom> }) {
  const [open, setOpen] = useState(false)
  return (
    <details className="disclosure plain voice-drill" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <h3>Your voice</h3>
        <span className="summary-meta muted small">graph and playback</span>
        <Chevron />
      </summary>
      {open && (
        <>
          <TurnVoice
            voiceUrl={api.drillVoiceUrl(packId, attemptId)}
            audioUrl={api.drillAudioUrl(packId, attemptId)}
            peerVoiceUrl={from ? api.turnVoiceUrl(from.session, from.turn) : undefined}
            title="This attempt"
            unavailableText="The voice graph isn't available for this attempt."
            noAdviceNote={null}
          />
          {from && (
            <TurnVoice
              voiceUrl={api.turnVoiceUrl(from.session, from.turn)}
              audioUrl={api.turnAudioUrl(from.session, from.turn)}
              peerVoiceUrl={api.drillVoiceUrl(packId, attemptId)}
              title="In the interview"
              noAdviceNote={null}
            />
          )}
        </>
      )}
    </details>
  )
}
