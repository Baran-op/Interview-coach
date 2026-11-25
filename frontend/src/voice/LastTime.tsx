import { useEffect, useState } from 'react'
import { api, type AnswerFeedback, type TurnVoice, type VoiceSection } from '../api'
import { questionOfTurn, questionsFromReport, type From } from './answers'
import { sectionWords } from './TurnVoice'
import { fmtClock } from './scale'

/** What the Drill comparison needs from the interview answer a "Try again in Drill" link came from. */
export interface LastInfo {
  pitchRange: number | null
  usual: number | null
  /** Flat stretches in the interview answer; null when the report doesn't say. */
  sections: number | null
}

interface Props {
  from: From
  onInfo?: (info: LastInfo | null) => void
}

type State = { state: 'loading' } | { state: 'error' } | { state: 'ready'; answer: AnswerFeedback | null; voice: TurnVoice | null }

/** "Last time" box in Drill: the interview's numbers, the flat stretch and what to stress. Defensive: every field may be missing. */
export default function LastTime({ from, onInfo }: Props) {
  const [st, setSt] = useState<State>({ state: 'loading' })

  useEffect(() => {
    let dead = false
    setSt({ state: 'loading' })
    void (async () => {
      try {
        const [session, rep] = await Promise.all([api.getSession(from.session), api.getReport(from.session)])
        const answers = rep.status === 'ready' && rep.report ? rep.report.answers : []
        const qs = questionsFromReport(answers, session.turns)
        const i = questionOfTurn(qs, from.turn)
        const answer = i >= 0 && qs[i].answerIdx != null ? answers[qs[i].answerIdx!] : null
        // The words of the stretch come from the turn's word offsets, which the stored section may not carry.
        const voice = from.section ? await api.getTurnVoice(from.session, from.turn).catch(() => null) : null
        if (dead) return
        setSt({ state: 'ready', answer, voice })
        const d = answer?.delivery
        onInfo?.({
          pitchRange: d?.voice?.pitch_range_st ?? null,
          usual: d?.voice_usual?.pitch_range_st ?? null,
          sections: d?.voice?.sections ? d.voice.sections.length : null,
        })
      } catch {
        if (!dead) {
          setSt({ state: 'error' })
          onInfo?.(null)
        }
      }
    })()
    return () => {
      dead = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from.session, from.turn, from.section])

  if (st.state === 'loading') return <p className="muted small last-time">Loading last time…</p>
  if (st.state === 'error') return <p className="muted small last-time">Couldn&apos;t load the interview this link came from.</p>

  const d = st.answer?.delivery
  const stored: VoiceSection[] = [...(d?.voice?.sections ?? []), ...(st.voice?.sections ?? [])]
  const sec = from.section ? (st.voice?.sections ?? []).find((s) => s.id === from.section) ?? stored.find((s) => s.id === from.section) : undefined
  const ordered = [...(st.voice?.sections ?? d?.voice?.sections ?? [])].sort((a, b) => a.start_ms - b.start_ms)
  const n = sec ? ordered.findIndex((s) => s.id === sec.id) + 1 : 0
  const advice = sec?.advice ?? stored.find((s) => s.id === from.section && s.advice)?.advice ?? null
  const said = sec ? sectionWords(sec, st.voice) : ''
  const range = d?.voice?.pitch_range_st
  const usual = d?.voice_usual?.pitch_range_st

  return (
    <div className="last-time">
      <strong>Last time</strong>
      <p className="small">
        {range != null ? (
          <>
            In the interview: pitch range {range.toFixed(1)} st{usual != null && ` (usual ${usual.toFixed(1)})`}.{' '}
          </>
        ) : (
          'In the interview: no pitch range was measured for this answer. '
        )}
        {sec && (
          <>
            Flat {n > 0 ? n : ''} at {fmtClock(sec.start_ms)}–{fmtClock(sec.end_ms)}
            {said && (
              <>
                : “{said}”
              </>
            )}
            .{' '}
          </>
        )}
        {advice?.stress?.length ? (
          <>
            Try stressing <em>{advice.stress.join(', ')}</em>
            {advice.say_it && (
              <>
                : “{advice.say_it}”
              </>
            )}
            .
          </>
        ) : null}
      </p>
    </div>
  )
}
