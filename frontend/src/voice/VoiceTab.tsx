import { useMemo, useState } from 'react'
import Dropdown from '../components/Dropdown'
import { api, categoryLabel, VOICE_FLAG_LABEL, type AnswerFeedback, type ReportResponse, type SessionInfo, type VoiceSection } from '../api'
import { fromParam, questionsByTurn, questionsFromReport, type QuestionEntry } from './answers'
import TurnVoice from './TurnVoice'

interface Props {
  session: SessionInfo
  report: ReportResponse | null
  /** Selected question (index into the list), from the URL. */
  q: number | null
  onSelect: (i: number) => void
  /** Rewrites the report (1 Claude request); the page confirms first. */
  onRewrite: () => void
  /** Pause the Feedback tab's video when audio starts. */
  onPlayStart: () => void
}

const st = (n: number | null | undefined) => (n == null ? null : `${n.toFixed(1)} st`)

/** "3.1 st · usual 5.4 · flat · flat ×2" for a report answer, or '' with no voice stats. */
function rowStats(a: AnswerFeedback | undefined): string {
  const d = a?.delivery
  if (!d?.voice) return ''
  const bits: string[] = []
  const r = st(d.voice.pitch_range_st)
  if (r) bits.push(r + (d.voice_usual?.pitch_range_st != null ? ` · usual ${d.voice_usual.pitch_range_st.toFixed(1)}` : ''))
  for (const f of d.voice_flags ?? []) bits.push(VOICE_FLAG_LABEL[f])
  const n = d.voice.sections?.length ?? 0
  if (n > 0) bits.push(`flat ×${n}`)
  return bits.join(' · ')
}

export default function VoiceTab({ session, report, q, onSelect, onRewrite, onPlayStart }: Props) {
  const ready = report?.status === 'ready' && !!report.report
  const r = ready ? report!.report! : null
  const entries: QuestionEntry[] = useMemo(() => (r ? questionsFromReport(r.answers, session.turns) : questionsByTurn(session.turns)), [r, session.turns])
  const [flatSeen, setFlatSeen] = useState<Record<string, number>>({})

  const candidates = session.turns.filter((t) => t.speaker === 'candidate')
  if (candidates.length === 0 || candidates.every((t) => t.has_audio === false)) {
    return <p className="muted">This session has no saved answer audio.</p>
  }

  const idx = Math.min(Math.max(q ?? 0, 0), Math.max(0, entries.length - 1))
  const entry = entries[idx]
  const answer = entry && entry.answerIdx != null ? r?.answers[entry.answerIdx] : undefined
  const anyAdvice = !!r?.answers.some((a) => a.delivery?.voice?.sections?.some((s) => s.advice))
  const noAdviceNote = !r
    ? 'Advice appears once the report is written.'
    : anyAdvice
      ? 'Lower priority: no advice was written for this stretch.'
      : 'No advice for this stretch: the report was written before voice advice.'
  const seen = entry ? (flatSeen[entry.key] ?? 0) : 0
  const sub = (e: QuestionEntry) => {
    const a = e.answerIdx != null ? r?.answers[e.answerIdx] : undefined
    if (e.turns.length === 0) return 'no answer'
    if (e.turns.every((t) => t.turn.has_audio === false)) return 'typed · no audio'
    return rowStats(a) || (r ? 'no pitch stats' : '')
  }

  const drillQuestionHref = (e: QuestionEntry) =>
    `#/drill/${session.pack_id}?q=${encodeURIComponent(e.question)}` + (e.turns[0] ? `&from=${encodeURIComponent(fromParam(session.id, e.turns[0].turn.idx))}` : '')

  const summary: string[] = []
  if (answer?.delivery?.voice) {
    const d = answer.delivery
    if (d.voice?.pitch_range_st != null) summary.push(`Pitch range ${d.voice.pitch_range_st.toFixed(1)} st` + (d.voice_usual?.pitch_range_st != null ? ` · your usual ${d.voice_usual.pitch_range_st.toFixed(1)}` : ''))
    for (const f of d.voice_flags ?? []) summary.push(VOICE_FLAG_LABEL[f])
    const n = d.voice?.sections?.length ?? 0
    if (n > 0) summary.push(`${n} flat ${n === 1 ? 'stretch' : 'stretches'}`)
  }

  return (
    <div className="voice-tab">
      {!ready && report?.status !== 'none' && (
        <p className="muted small voice-note">
          {report?.status === 'error' ? 'The report failed, so the list is grouped by turn.' : 'The list is grouped by turn until the report is ready.'}
        </p>
      )}
      <nav className="voice-list voice-list-wide card" aria-label="Questions">
        <h3>Questions</h3>
        {entries.map((e, i) => (
          <button key={e.key} className={`voice-q ${i === idx ? 'on' : ''}`} aria-current={i === idx} onClick={() => onSelect(i)}>
            <span className="voice-q-title">
              <span className="answer-n">{i + 1}</span> {e.question}
            </span>
            <span className="voice-q-sub muted small">{sub(e)}</span>
            {e.turns.slice(1).map((t) => (
              <span key={t.turn.idx} className="voice-q-sub muted small">
                └ follow-up {t.n}
              </span>
            ))}
          </button>
        ))}
      </nav>
      <div className="voice-list-narrow field">
        <Dropdown
          ariaLabel="Question"
          value={idx}
          onChange={onSelect}
          options={entries.map((e, i) => ({ value: i, label: `${i + 1} · ${e.question.length > 70 ? `${e.question.slice(0, 70)}…` : e.question}`, hint: sub(e) || undefined }))}
        />
      </div>

      {entry && (
        <section className="voice-detail card">
          <div className="voice-detail-head">
            <div>
              {answer?.category && r && (
                <span className="eyebrow">
                  {idx + 1} · {categoryLabel(answer.category, r)}
                </span>
              )}
              <h3>{entry.question}</h3>
              {summary.length > 0 && <p className="small">{summary.join(' · ')}</p>}
            </div>
            {entry.turns.length > 0 && (
              <a className="button-link small" href={drillQuestionHref(entry)}>
                Try again in Drill ↗
              </a>
            )}
          </div>

          {r && !anyAdvice && seen > 0 && (
            <div className="banner">
              Write report again for voice advice: 1 Claude request, scores may shift.{' '}
              <button className="small" onClick={onRewrite}>
                Write report again (1 request)
              </button>
            </div>
          )}

          {entry.turns.length === 0 && <p className="muted small">No answer was recorded for this question.</p>}
          {entry.turns.map((t) => {
            const stored: VoiceSection[] = (answer?.delivery?.voice?.sections ?? []).filter((s) => s.turn_idx == null || s.turn_idx === t.turn.idx)
            const title = t.kind === 'main' ? (r ? 'Main answer' : 'Your answer') : `Follow-up ${t.n}${t.prompt ? `: “${t.prompt.length > 140 ? `${t.prompt.slice(0, 140)}…` : t.prompt}”` : ''}`
            return (
              <TurnVoice
                key={`${session.id}-${t.turn.idx}`}
                voiceUrl={api.turnVoiceUrl(session.id, t.turn.idx)}
                audioUrl={api.turnAudioUrl(session.id, t.turn.idx)}
                title={title}
                fallbackText={t.turn.text}
                storedSections={stored}
                usualWindowSt={answer?.delivery?.voice_usual?.window_range_st ?? null}
                noAdviceNote={noAdviceNote}
                drillHref={(sid) => `#/drill/${session.pack_id}?q=${encodeURIComponent(entry.question)}&from=${encodeURIComponent(fromParam(session.id, t.turn.idx, sid))}`}
                onPlayStart={onPlayStart}
                onSections={(n) => setFlatSeen((m) => (n > (m[entry.key] ?? 0) ? { ...m, [entry.key]: n } : m))}
              />
            )
          })}
        </section>
      )}
    </div>
  )
}
