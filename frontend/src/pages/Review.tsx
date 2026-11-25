import { useEffect, useMemo, useRef, useState } from 'react'
import { Chevron } from '../components/Dropdown'
import { getRecordMode } from '../audio/recorder'
import { api, CATEGORY_LABEL, FACE_FLAG_LABEL, FACE_MOMENT_LABEL, VOICE_FLAG_LABEL, faceTooltip, voiceTooltip, type AnswerDelivery, type FaceFlag, type FaceMoment, type Criterion, type HistorySession, type Pack, type ReportResponse, type SessionInfo, type Turn, type VoiceFlag } from '../api'

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
  const [duration, setDuration] = useState(0)
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
    if (Number.isFinite(v.duration)) setDuration(v.duration * 1000)
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
  const allMoments = (report?.report?.answers ?? []).flatMap((a) => a.delivery?.face?.moments ?? [])
  const timelineMs = duration || (session.ended_at ? session.ended_at - session.started_at : 0)
  const avatarNote = getRecordMode() === 'avatar'
  const turnTime = (idx: number | null) => turns.find((t) => t.idx === idx)?.t_start_ms ?? null

  return (
    <div className="review">
      <div className="review-head card">
        <h2>
          <span className="eyebrow">Session review</span>
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
              onDurationChange={(e) => Number.isFinite(e.currentTarget.duration) && setDuration(e.currentTarget.duration * 1000)}
              onTimeUpdate={(e) => setNowMs(e.currentTarget.currentTime * 1000)}
            />
            {allMoments.length > 0 && timelineMs > 0 && (
              <div className="moment-bands" aria-label="Moments on the recording">
                {allMoments.map((m, i) => (
                  <button
                    key={i}
                    className="moment-band"
                    title={momentText(m)}
                    aria-label={momentText(m)}
                    style={{ left: `${Math.min(100, (m.start_ms / timelineMs) * 100)}%`, width: `${Math.max(0.5, Math.min(100, ((m.end_ms - m.start_ms) / timelineMs) * 100))}%` }}
                    onClick={() => seek(m.start_ms)}
                  />
                ))}
              </div>
            )}
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

        <details className="disclosure plain" open>
          <summary>
            <h3>Transcript</h3>
            <span className="summary-meta muted small">{turns.length} turns</span>
            <Chevron />
          </summary>
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
        </details>
      </section>

      <section className="card report">
        <h2 className="section-title">Feedback</h2>
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
            {voiceSummary(r.answers) && <p className="small">Voice: {voiceSummary(r.answers)}</p>}
            {faceSummary(r.answers) && <p className="small">Face: {faceSummary(r.answers)}</p>}
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
              const avg = CRITERIA.reduce((n, c) => n + a.scores[c], 0) / CRITERIA.length
              return (
                <details key={i} className="answer disclosure" open={i === 0 || undefined}>
                  <summary>
                    <span className="answer-n">{i + 1}</span>
                    <strong className="answer-title">{a.question}</strong>
                    <span className="score-chip" title="Average of the four criteria">
                      {avg.toFixed(1)}
                    </span>
                    <Chevron />
                  </summary>
                  <div className="answer-tools">
                    {a.category && (
                      <span className="chip" title={a.competency || undefined}>
                        {CATEGORY_LABEL[a.category] ?? a.category}
                        {a.competency ? ` · ${a.competency}` : ''}
                      </span>
                    )}
                    {session.has_recording && at != null && (
                      <button className="small" onClick={() => seek(at)}>
                        ▶ Play from {clock(at)}
                      </button>
                    )}
                    <a className="button-link small" href={`#/drill/${session.pack_id}?q=${encodeURIComponent(a.question)}`}>
                      Practise this question
                    </a>
                  </div>
                  <div className="bars">
                    {CRITERIA.map((c) => (
                      <FragmentBar key={c} label={LABEL[c]} value={a.scores[c]} />
                    ))}
                  </div>
                  {a.delivery && <DeliveryLine d={a.delivery} />}
                  {(a.delivery?.face?.moments?.length ?? 0) > 0 && (
                    <MomentList
                      moments={a.delivery!.face!.moments!}
                      canSeek={session.has_recording}
                      onSeek={seek}
                      note={avatarNote && i === firstMomentAnswer(r.answers)}
                    />
                  )}
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
                </details>
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

/** "flat in 3 of 7 answers, trailing off in 2" over the answers that have voice stats, or '' if none do. */
function voiceSummary(answers: { delivery?: AnswerDelivery }[]): string {
  const measured = answers.filter((a) => a.delivery?.voice)
  if (measured.length === 0) return ''
  const count = (f: VoiceFlag) => measured.filter((a) => a.delivery?.voice_flags?.includes(f)).length
  const bits = (['flat', 'lively', 'trailing'] as VoiceFlag[])
    .filter((f) => count(f) > 0)
    .map((f) => `${VOICE_FLAG_LABEL[f]} in ${count(f)}${f === 'flat' ? ` of ${measured.length} answers` : ''}`)
  return bits.length ? bits.join(', ') : `no flags in ${measured.length} answers`
}

/** "eye contact 58%" etc. over the answers that have face stats, or '' if none do. */
function faceSummary(answers: { delivery?: AnswerDelivery }[]): string {
  const measured = answers.filter((a) => a.delivery?.face && a.delivery.face.on_screen_pct != null)
  if (measured.length === 0) return ''
  const count = (f: FaceFlag) => measured.filter((a) => a.delivery?.face_flags?.includes(f)).length
  const avg = Math.round(measured.reduce((n, a) => n + a.delivery!.face!.on_screen_pct!, 0) / measured.length)
  const bits = (['looking_down', 'low_eye_contact', 'still'] as FaceFlag[])
    .filter((f) => count(f) > 0)
    .map((f) => `${FACE_FLAG_LABEL[f]} in ${count(f)} of ${measured.length} answers`)
  return `eye contact ${avg}% on average` + (bits.length ? `, ${bits.join(', ')}` : '')
}

const firstMomentAnswer = (answers: { delivery?: AnswerDelivery }[]) =>
  answers.findIndex((a) => (a.delivery?.face?.moments?.length ?? 0) > 0)

const momentText = (m: FaceMoment) =>
  `${FACE_MOMENT_LABEL[m.kind]} ${clock(m.start_ms)}\u2013${clock(m.end_ms)} (${Math.max(0, Math.round((m.end_ms - m.start_ms) / 1000))} s)`

/** Where in the recording the face stats went off, each with a button that plays it. */
function MomentList({ moments, canSeek, onSeek, note }: { moments: FaceMoment[]; canSeek: boolean; onSeek: (ms: number) => void; note: boolean }) {
  return (
    <div className="moments small">
      {note && <p className="muted small">This recording shows the avatar, not you, so the times below are for reference. Record with the webcam to watch them.</p>}
      <ul>
        {moments.map((m, i) => (
          <li key={i}>
            {momentText(m)}
            {m.quote && (
              <>
                , while saying: <em>{'\u201c'}{m.quote}{'\u201d'}</em>
              </>
            )}{' '}
            {canSeek && (
              <button className="small ghost" aria-label={`Play from ${clock(m.start_ms)}`} onClick={() => onSeek(m.start_ms)}>
                ▶
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
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
  const voiceTip = voiceTooltip(d)
  const flags = d.voice_flags ?? []
  const faceFlags = d.face_flags ?? []
  const eye = d.face?.on_screen_pct
  return (
    <p className="small delivery-line" title={d.flag ? `This answer was too ${d.flag} for its question type` : undefined}>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && ' · '}
          <span className={p.bad ? 'out-of-target' : undefined}>{p.text}</span>
        </span>
      ))}
      {flags.length > 0 && (
        <span title={voiceTip || undefined}>
          {' · voice: '}
          {flags.map((f, i) => (
            <span key={f}>
              {i > 0 && ', '}
              <span className="out-of-target">{VOICE_FLAG_LABEL[f]}</span>
            </span>
          ))}
        </span>
      )}
      {(eye != null || faceFlags.length > 0) && (
        <span title={faceTooltip(d) || undefined}>
          {eye != null && ` · eye contact ${Math.round(eye)}%`}
          {faceFlags
            .filter((f) => f !== 'low_eye_contact')
            .map((f) => (
              <span key={f}>
                {' · '}
                <span className="out-of-target">{FACE_FLAG_LABEL[f]}</span>
              </span>
            ))}
        </span>
      )}
    </p>
  )
}
