import { useEffect, useMemo, useRef, useState } from 'react'
import { api, CATEGORY_LABEL, type AnswerDelivery, type Criterion, type HistorySession, type Pack, type ReportResponse, type SessionInfo, type Turn } from '../api'

const CRITERIA: Criterion[] = ['relevance', 'structure', 'specificity', 'evidence']
const LABEL: Record<Criterion, string> = {
  relevance: 'Relevance',
  structure: 'Structure',
  specificity: 'Specificity',
  evidence: 'Evidence',
}

function clock(ms: number | null) {
  if (ms == null) return ''
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

interface Props {
  sessionId: string
  onStart: (pack: Pack) => void
}

export default function Review({ sessionId, onStart }: Props) {
  const [session, setSession] = useState<SessionInfo | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nowMs, setNowMs] = useState(0)
  const [audioOnly, setAudioOnly] = useState(false)
  const [isPartial, setIsPartial] = useState(false)
  const [previous, setPrevious] = useState<HistorySession | null>(null)
  const video = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    api.getSession(sessionId).then(setSession, (e: Error) => setError(e.message))
  }, [sessionId])

  // The previous scored attempt at the same pack, for comparison.
  const packId = session?.pack_id
  const reportReady = report?.status === 'ready'
  useEffect(() => {
    if (!packId || !session) return
    api
      .packHistory(packId)
      .then((h) => {
        const earlier = h.filter((s) => s.started_at < session.started_at && s.overall_score != null && s.criteria && !s.partial)
        setIsPartial(h.find((s) => s.id === session.id)?.partial ?? false)
        setPrevious(earlier[earlier.length - 1] ?? null)
      })
      .catch(() => {})
  }, [packId, session, reportReady])

  // Poll until the report is written.
  useEffect(() => {
    let stop = false
    let timer = 0
    const poll = async () => {
      try {
        const r = await api.getReport(sessionId)
        if (stop) return
        setReport(r)
        if (r.status === 'pending') timer = window.setTimeout(poll, 2500)
      } catch (e) {
        if (!stop) setError((e as Error).message)
      }
    }
    void poll()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [sessionId])

  const turns = session?.turns ?? []
  const timed = turns.some((t) => t.t_start_ms != null)
  const questions = useMemo(() => {
    let n = 0
    return turns
      .filter((t) => t.speaker === 'interviewer' && t.t_start_ms != null)
      .map((t) => ({ turn: t, label: t.text.includes('?') ? `Q${++n}` : '•' }))
  }, [turns])
  const active = useMemo(() => {
    let cur: Turn | null = null
    for (const t of turns) if (t.t_start_ms != null && t.t_start_ms <= nowMs + 150) cur = t
    return cur?.idx ?? null
  }, [turns, nowMs])

  const seek = (ms: number | null) => {
    const v = video.current
    if (!v || ms == null) return
    v.currentTime = Math.max(0, ms / 1000 - 0.3)
    void v.play()
  }

  // MediaRecorder files have no duration in their header: Chrome reports
  // Infinity until it has scanned the file once. Seeking far forward forces that.
  const onMetadata = () => {
    const v = video.current
    if (!v) return
    setAudioOnly(v.videoWidth === 0)
    if (v.duration === Infinity) {
      const reset = () => {
        v.removeEventListener('timeupdate', reset)
        v.currentTime = 0
      }
      v.addEventListener('timeupdate', reset)
      v.currentTime = 1e101
    }
  }

  const regenerate = async () => {
    setError(null)
    try {
      await api.regenerateReport(sessionId)
      setReport({ status: 'pending', report: null, report_md: null, error: null })
      const poll = async () => {
        const r = await api.getReport(sessionId)
        setReport(r)
        if (r.status === 'pending') window.setTimeout(poll, 2500)
      }
      window.setTimeout(poll, 2500)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error && !session) return <div className="banner error">{error}</div>
  if (!session) return <p className="muted">Loading…</p>

  const pack = session.pack
  const r = report?.report
  const turnTime = (idx: number | null) => turns.find((t) => t.idx === idx)?.t_start_ms ?? null

  return (
    <div className="review">
      <div className="review-head card">
        <h2>
          {pack?.title ?? 'Interview'}
          <div className="muted small">
            {new Date(session.started_at).toLocaleString()}
            {session.ended_at ? ` · ${clock(session.ended_at - session.started_at)} long` : ''}
          </div>
        </h2>
        <div className="actions">
          <a
            className={`button-link ${session.has_recording ? '' : 'disabled'}`}
            href={api.recordingUrl(sessionId, true)}
            download
          >
            Download recording (.webm)
          </a>
          <a className={`button-link ${report?.report_md ? '' : 'disabled'}`} href={api.reportMdUrl(sessionId)} download>
            Download report (.md)
          </a>
          {pack && (
            <button className="primary" onClick={() => onStart(pack)}>
              Run this pack again
            </button>
          )}
          <button
            className="ghost"
            onClick={async () => {
              if (!window.confirm('Delete this session with its recording and report?')) return
              try {
                await api.deleteSession(sessionId)
                window.location.hash = '#/history'
              } catch (e) {
                setError((e as Error).message)
              }
            }}
          >
            Delete
          </button>
        </div>
      </div>

      <section className="card">
        {session.has_recording ? (
          <div className="player">
            <video
              ref={video}
              className={audioOnly ? 'audio-only' : ''}
              src={api.recordingUrl(sessionId)}
              controls
              preload="metadata"
              onLoadedMetadata={onMetadata}
              onTimeUpdate={(e) => setNowMs(e.currentTarget.currentTime * 1000)}
            />
            {questions.length > 0 && (
              <div className="markers">
                {questions.map((q) => (
                  <button
                    key={q.turn.idx}
                    className={`marker ${active === q.turn.idx ? 'active' : ''}`}
                    title={q.turn.text}
                    onClick={() => seek(q.turn.t_start_ms)}
                  >
                    {q.label} <span className="muted">{clock(q.turn.t_start_ms)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="muted">No recording for this session.</p>
        )}

        <h3>Transcript</h3>
        <div className="turns">
          {turns.map((t) => (
            <button
              key={t.idx}
              className={`turn ${t.speaker} ${active === t.idx ? 'active' : ''}`}
              onClick={() => seek(t.t_start_ms)}
              disabled={!session.has_recording || t.t_start_ms == null}
            >
              <span className="t">{timed ? clock(t.t_start_ms) : ''}</span>
              <span>
                <span className="who">{t.speaker === 'interviewer' ? pack?.options.interviewer_name || 'Interviewer' : 'You'}</span>
                <br />
                {t.text}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="card report">
        <h2>Feedback</h2>
        {error && <div className="banner error">{error}</div>}
        {(!report || report.status === 'pending') && (
          <p className="muted">Writing your feedback… This usually takes under a minute.</p>
        )}
        {report && (report.status === 'error' || report.status === 'none') && (
          <div className="banner error">
            {report.error ?? 'No report yet.'}{' '}
            <button onClick={() => void regenerate()}>{report.status === 'none' ? 'Write report' : 'Try again'}</button>
          </div>
        )}
        {r && (
          <>
            <div className="overall">
              <div className="big-score">
                {r.overall_score.toFixed(1)}
                <small> / 5</small>
              </div>
              <p>{r.summary}</p>
            </div>
            {isPartial && (
              <div className="banner">
                Too few answers to count: this session is marked partial and is left out of your history trends.
              </div>
            )}
            {previous && <Comparison report={r} previous={previous} />}

            {(r.previous_fixes?.length ?? 0) > 0 && (
              <>
                <h3>Since last time</h3>
                <ul className="fixes">
                  {r.previous_fixes!.map((p, i) => (
                    <li key={i}>
                      <strong>
                        {{ improved: '✓ Improved', partly: '~ Partly', not_yet: '✗ Not yet', not_tested: '– Not tested' }[p.status]}:
                      </strong>{' '}
                      {p.fix}
                      {p.evidence && <span className="muted"> ({p.evidence})</span>}
                    </li>
                  ))}
                </ul>
              </>
            )}

            <h3>Top 3 things to fix</h3>
            <ol className="fixes">
              {r.top_fixes.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ol>

            <h3>Delivery</h3>
            <div className="stats">
              <div className="stat">
                <div className="n">{r.filler_words.count}</div>
                <div className="muted small">
                  filler words
                  {r.filler_words.count > 0 &&
                    ` (${Object.entries(r.filler_words.by_word ?? {})
                      .map(([w, n]) => `${w} ×${n}`)
                      .join(', ')})`}
                </div>
              </div>
              {r.avg_answer_seconds != null && (
                <div className="stat">
                  <div className="n">{Math.round(r.avg_answer_seconds)} s</div>
                  <div className="muted small">average answer length</div>
                </div>
              )}
            </div>
            {r.filler_words.examples.length > 0 && (
              <ul className="muted small">
                {r.filler_words.examples.map((ex, i) => (
                  <li key={i}>“{ex}”</li>
                ))}
              </ul>
            )}

            <h3>Your answers</h3>
            {r.answers.map((a, i) => {
              const at = turnTime(a.question_turn)
              return (
                <div key={i} className="answer">
                  <div className="answer-q">
                    <strong>
                      {i + 1}. {a.question}
                    </strong>
                    <span className="chip" title={a.competency || undefined}>
                      {CATEGORY_LABEL[a.category] ?? a.category}
                      {a.competency ? ` · ${a.competency}` : ''}
                    </span>
                    {session.has_recording && at != null && (
                      <button className="ghost small" onClick={() => seek(at)}>
                        ▶ {clock(at)}
                      </button>
                    )}
                  </div>
                  <div className="bars">
                    {CRITERIA.map((c) => (
                      <FragmentBar key={c} label={LABEL[c]} value={a.scores[c]} />
                    ))}
                  </div>
                  {a.delivery && <DeliveryLine d={a.delivery} />}
                  <p className="small">{a.answer_summary}</p>
                  {a.tips.length > 0 && (
                    <ul className="small">
                      {a.tips.map((t, j) => (
                        <li key={j}>{t}</li>
                      ))}
                    </ul>
                  )}
                  {a.better_answer && (
                    <details className="better">
                      <summary>A stronger answer</summary>
                      <p>{a.better_answer}</p>
                    </details>
                  )}
                </div>
              )
            })}
          </>
        )}
      </section>
    </div>
  )
}

function Delta({ label, now, before }: { label: string; now: number; before: number }) {
  const d = Math.round((now - before) * 10) / 10
  const cls = d > 0 ? 'up' : d < 0 ? 'down' : ''
  return (
    <span>
      {label}{' '}
      <span className={`delta ${cls}`}>
        {d > 0 ? '▲' : d < 0 ? '▼' : '='} {d > 0 ? '+' : ''}
        {d.toFixed(1)}
      </span>
    </span>
  )
}

/** Change since the previous attempt at the same pack. */
function Comparison({ report, previous }: { report: NonNullable<ReportResponse['report']>; previous: HistorySession }) {
  const avg = (c: Criterion) => report.answers.reduce((n, a) => n + a.scores[c], 0) / report.answers.length
  return (
    <div className="compare">
      <div className="muted small">
        Compared with your previous attempt ({new Date(previous.started_at).toLocaleDateString()},{' '}
        {previous.overall_score!.toFixed(1)}): <a href="#/history">see all</a>
      </div>
      <div className="deltas">
        <Delta label="Overall" now={report.overall_score} before={previous.overall_score!} />
        {CRITERIA.map((c) => (
          <Delta key={c} label={LABEL[c]} now={avg(c)} before={previous.criteria![c]} />
        ))}
        {previous.filler_count != null && (
          <span>
            Fillers {report.filler_words.count} (was {previous.filler_count})
          </span>
        )}
      </div>
    </div>
  )
}

function FragmentBar({ label, value }: { label: string; value: number }) {
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

const mmss = (s: number) => `${Math.floor(Math.round(s) / 60)}:${String(Math.round(s) % 60).padStart(2, '0')}`

/** Per-answer delivery stats; length outside the target is highlighted. */
function DeliveryLine({ d }: { d: AnswerDelivery }) {
  const n = (c: number, w: string) => `${c} ${w}${c === 1 ? '' : 's'}`
  const parts: { text: string; bad?: boolean }[] = [
    {
      text: mmss(d.first_answer_seconds) + (d.target ? ` (aim ${mmss(d.target[0])}-${mmss(d.target[1])})` : ''),
      bad: d.flag !== null,
    },
  ]
  if (d.wpm) parts.push({ text: `${d.wpm} wpm`, bad: d.wpm > 180 || d.wpm < 100 })
  parts.push({ text: `I ${d.i_count} / we ${d.we_count}`, bad: d.we_count > d.i_count })
  parts.push({ text: n(d.numbers, 'number'), bad: d.numbers === 0 })
  parts.push({ text: n(d.fillers, 'filler'), bad: d.fillers >= 5 })
  parts.push({ text: n(d.hedges, 'hedge'), bad: d.hedges >= 3 })
  if (d.pauses_over_1s) parts.push({ text: n(d.pauses_over_1s, 'long pause'), bad: true })
  return (
    <p className="small delivery-line" title={d.flag ? `This answer was too ${d.flag} for its question type` : undefined}>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && ' · '}
          <span className={p.bad ? 'out-of-target' : undefined}>{p.text}</span>
        </span>
      ))}
    </p>
  )
}
