import type { Pack } from './api'

const STAGE_LABEL: Record<string, string> = { screen: 'Screening call', full: 'Full interview', final: 'Final round' }
const TYPE_LABEL: Record<string, string> = { behavioural: 'Behavioural', technical: 'Technical', mixed: 'Mixed', case: 'Case', roleplay: 'Role-play' }
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)

/** A pack's format in words: "Full interview · Mixed · 5 questions · Medium difficulty · Neutral interviewer". */
export function packSummary(p: Pack) {
  const o = p.options
  const m = p.brief_meta
  const tail = [`${cap(o.difficulty)} difficulty`, `${cap(o.style)} interviewer`]
  if (m?.exists && m.kind === 'stations') {
    const mins = [...new Set(m.stations.map((s) => s.minutes))]
    const each = mins.length === 1 ? `${m.stations.length} stations × ${mins[0]} min` : `${m.stations.length} stations, ${m.total_minutes} min`
    return [each, ...tail].join(' · ')
  }
  const length = o.minutes ? `${o.minutes} min` : `${o.num_questions} questions`
  return [STAGE_LABEL[o.stage ?? 'full'] ?? o.stage, TYPE_LABEL[o.interview_type] ?? o.interview_type, length, ...tail].join(' · ')
}

/** "N to confirm" and "Brief out of date" badges; each opens the brief. */
export function PackBadges({ pack }: { pack: Pack }) {
  const m = pack.brief_meta
  if (!m?.exists || (m.to_confirm === 0 && !m.stale)) return null
  return (
    <span className="badges">
      {m.to_confirm > 0 && (
        <a className="badge" href={`#/brief/${pack.id}`} title={`${m.to_confirm} assumption${m.to_confirm === 1 ? '' : 's'} in the interview brief to confirm`}>
          {m.to_confirm} to confirm
        </a>
      )}
      {m.stale && (
        <a className="badge" href={`#/brief/${pack.id}`} title="Your materials changed since the interview brief was written">
          Brief out of date
        </a>
      )}
    </span>
  )
}
