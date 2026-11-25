import { useCallback, useEffect, useRef, useState } from 'react'
import { api, CATEGORY_LABEL, type Criterion, type DrillAttempt, type DrillQuestion, type Pack } from '../api'
import { InterviewerPlayer, type Speaker } from '../audio/player'
import { TurnListener } from '../audio/vad'
import { encodeWav } from '../audio/wav'
import { Avatar, AvatarController, avatarAvailable } from '../avatar/Avatar'

const CRITERIA: Criterion[] = ['relevance', 'structure', 'specificity', 'evidence']
const LABEL: Record<Criterion, string> = {
  relevance: 'Relevance',
  structure: 'Structure',
  specificity: 'Specificity',
  evidence: 'Evidence',
}

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
}

export default function Drill({ packId, initialQuestion }: Props) {
  const [pack, setPack] = useState<Pack | null>(null)
  const [questions, setQuestions] = useState<DrillQuestion[]>([])
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

  const playerRef = useRef<InterviewerPlayer | null>(null)
  const avatarRef = useRef<AvatarController | null>(null)
  const listenerRef = useRef<TurnListener | null>(null)
  const currentRef = useRef<Current | null>(null)
  currentRef.current = current

  const player = () => (playerRef.current ??= new InterviewerPlayer())
  const speaker = (): Speaker => avatarRef.current ?? player()

  const refreshQuestions = useCallback(async () => {
    setQuestions((await api.drillQuestions(packId)).questions)
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
        if (initialQuestion) {
          const key = await questionKey(initialQuestion)
          const known = q.questions.find((x) => x.key === key)
          await select(known?.question ?? initialQuestion, known?.category ?? null, key)
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

  const playQuestion = async () => {
    if (!current || !pack) return
    setError(null)
    await player().unlock()
    setPhase('speaking')
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
    setPhase((p) => (p === 'speaking' ? 'idle' : p))
  }

  const submit = async (a: { text?: string; wav?: Blob; seconds?: number }) => {
    const cur = currentRef.current
    if (!cur) return
    setPhase('scoring')
    setError(null)
    try {
      const r = await api.drillAttempt(packId, { question: cur.question, category: cur.category, ...a })
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
            onTurn: (audio) => void submit({ wav: encodeWav(audio), seconds: audio.length / 16000 }),
            onEmpty: () => {
              setNotice("I didn't hear anything. Try again.")
              setPhase('idle')
            },
          },
          0, // Done-only: thinking pauses are normal in a drill
        )
        await l.init()
        listenerRef.current = l
      }
      setNotice(null)
      setPhase('listening')
      await listenerRef.current.listen()
    } catch (e) {
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
      <div className="page-head">
        <div>
          <p className="eyebrow">Drill</p>
          <h1 className="page-title">{pack ? pack.title : 'Drill'}</h1>
          <p className="muted lede">Practise one question at a time. Each attempt you submit uses one Claude request.</p>
        </div>
      </div>
      {error && <div className="banner error">{error}</div>}
      <div className="drill-body">
        <aside className="card drill-list">
          <h2>Questions</h2>
          {questions.map((q) => (
            <button
              key={q.key}
              className={`drill-q ${current?.key === q.key ? 'on' : ''}`}
              onClick={() => void select(q.question, q.category, q.key)}
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
              {current.category && <span className="chip">{CATEGORY_LABEL[current.category] ?? current.category}</span>}
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
                    {result.previous?.result && (
                      <span className="chip">{delta(result.attempt.result.average - result.previous.result.average)} since last time</span>
                    )}
                  </h3>
                  <div className="bars">
                    {CRITERIA.map((c) => (
                      <Bar key={c} label={LABEL[c]} value={result.attempt.result!.scores[c]} />
                    ))}
                  </div>
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
                        const avg = a.result?.average ?? null
                        const prev = i > 0 ? (attempts[i - 1].result?.average ?? null) : null
                        return (
                          <tr key={a.id}>
                            <td>{i + 1}</td>
                            <td>{new Date(a.created_at).toLocaleString()}</td>
                            <td>{fmt(avg)}</td>
                            <td>{avg != null && prev != null ? delta(avg - prev) : ''}</td>
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
