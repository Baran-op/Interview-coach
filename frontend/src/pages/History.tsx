import { useEffect, useRef, useState } from 'react'
import { api, CATEGORY_LABEL, type Criterion, type HistorySession, type Pack, type PackHistory } from '../api'
import { Chevron } from '../components/Dropdown'
import { packSummary } from './Setup'

const CRITERIA: { key: Criterion; label: string }[] = [
  { key: 'relevance', label: 'Relevance' },
  { key: 'structure', label: 'Structure' },
  { key: 'specificity', label: 'Specificity' },
  { key: 'evidence', label: 'Evidence' },
]

const fmtDate = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
const fmtDateTime = (ms: number) => new Date(ms).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const fmtLen = (s: HistorySession) => {
  if (!s.ended_at) return '–'
  const sec = Math.round((s.ended_at - s.started_at) / 1000)
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`
}
const TYPE_COLORS = ['#2f6fed', '#d9730d', '#1a9e6b', '#c2410c', '#8b5cf6', '#0e7490', '#b91c1c', '#64748b']

interface TypeStat {
  category: string
  points: { s: HistorySession; value: number }[]
}

/** Per question type, the sessions that had it, oldest first. Callers pass counted (non-partial) sessions only. */
function typeStats(sessions: HistorySession[]): TypeStat[] {
  const by = new Map<string, TypeStat>()
  for (const s of sessions) {
    for (const [category, v] of Object.entries(s.by_category ?? {})) {
      if (!by.has(category)) by.set(category, { category, points: [] })
      by.get(category)!.points.push({ s, value: v.average })
    }
  }
  const order = Object.keys(CATEGORY_LABEL)
  return [...by.values()].sort((a, b) => order.indexOf(a.category) - order.indexOf(b.category))
}

/** Type, answers, first, latest and best score for each question type. Partial sessions are excluded by the caller. */
function TypeTable({ sessions }: { sessions: HistorySession[] }) {
  const rows = typeStats(sessions)
  if (!rows.length) return null
  return (
    <div className="type-table table-wrap">
      <h3>By question type</h3>
      <table className="sessions">
        <caption className="sr-only">Scores by question type</caption>
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col" className="num">Answers</th>
            <th scope="col" className="num">First</th>
            <th scope="col" className="num">Latest</th>
            <th scope="col" className="num">Best</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => {
            const vals = t.points.map((p) => p.value)
            const n = t.points.reduce((sum, p) => sum + (p.s.by_category[t.category]?.answers ?? 0), 0)
            return (
              <tr key={t.category}>
                <td>{CATEGORY_LABEL[t.category] ?? t.category}</td>
                <td className="num">{n}</td>
                <td className="num">{vals[0].toFixed(1)}</td>
                <td className="num strong">{vals[vals.length - 1].toFixed(1)}</td>
                <td className="num">{Math.max(...vals).toFixed(1)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const signed = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v).toFixed(1)}`

interface Props {
  onStart: (pack: Pack) => void
}

export default function History({ onStart }: Props) {
  const [data, setData] = useState<PackHistory[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => api.history().then(setData, (e: Error) => setError(e.message))
  useEffect(() => {
    void load()
  }, [])

  const deletePack = async (p: Pack, n: number) => {
    const what = n ? ` and its ${n} session${n > 1 ? 's' : ''} (recordings and reports)` : ''
    if (!window.confirm(`Delete the pack "${p.title}"${what}? This can't be undone.`)) return
    try {
      await api.deletePack(p.id)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const deleteSession = async (s: HistorySession) => {
    if (!window.confirm(`Delete the session from ${fmtDateTime(s.started_at)} with its recording and report?`)) return
    try {
      await api.deleteSession(s.id)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error && !data) return <div className="banner error">{error}</div>
  if (!data) return <p className="muted">Loading…</p>

  return (
    <div className="history">
      <div className="page-head">
        <div>
          <p className="eyebrow">Progress</p>
          <h1 className="page-title">History</h1>
          <p className="muted lede">Every pack you've practised, with scores over time.</p>
        </div>
      </div>
      {error && <div className="banner error">{error}</div>}
      {data.length === 0 && (
        <div className="card">
          <p className="muted">
            No interview packs yet. <a href="#/">Create one</a> to get started.
          </p>
        </div>
      )}
      {data.map(({ pack, sessions }) => {
        const scored = sessions.filter((s) => s.overall_score != null && !s.partial)
        const first = scored[0]?.overall_score ?? null
        const latest = scored[scored.length - 1]?.overall_score ?? null
        const best = scored.length ? Math.max(...scored.map((s) => s.overall_score!)) : null
        return (
          <section key={pack.id} className="card pack-history">
            <div className="ph-head">
              <div>
                <h2>{pack.title}</h2>
                <div className="muted small">
                  {[pack.role, pack.company].filter(Boolean).join(' at ')}
                  {pack.role || pack.company ? ' · ' : ''}
                  {packSummary(pack)}
                </div>
              </div>
              <div className="actions">
                <button className="primary" onClick={() => onStart(pack)}>
                  Run again
                </button>
                <a className="button-link" href={`#/drill/${pack.id}`}>
                  Drill
                </a>
                <a className="button-link" href={`#/prep/${pack.id}`}>
                  Prep
                </a>
                <a className="button-link" href={`#/edit/${pack.id}`}>
                  Edit
                </a>
                <button className="ghost" onClick={() => void deletePack(pack, sessions.length)}>
                  Delete
                </button>
              </div>
            </div>

            {sessions.length === 0 ? (
              <p className="muted">No finished sessions yet.</p>
            ) : (
              <>
                <div className="ph-stats">
                  <Stat label="sessions" value={String(sessions.length)} />
                  <Stat label="latest score" value={latest != null ? latest.toFixed(1) : '–'} />
                  <Stat label="best score" value={best != null ? best.toFixed(1) : '–'} />
                  {scored.length > 1 && first != null && latest != null && (
                    <Stat label="since first session" value={signed(latest - first)} />
                  )}
                </div>
                {scored.length > 1 && <ScoreChart sessions={sessions.filter((s) => s.overall_score != null)} />}
                <TypeTable sessions={scored} />
                <DeliveryTable sessions={scored} />
                <details className="disclosure plain" open>
                  <summary>
                    <h3>Sessions</h3>
                    <span className="summary-meta muted small">{sessions.length} total</span>
                    <Chevron />
                  </summary>
                <div className="table-wrap">
                  <table className="sessions">
                    <caption className="sr-only">Sessions for {pack.title}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Length</th>
                        <th scope="col" className="num">
                          Overall
                        </th>
                        {CRITERIA.map((c) => (
                          <th key={c.key} scope="col" className="num">
                            {c.label}
                          </th>
                        ))}
                        <th scope="col" className="num">
                          Fillers
                        </th>
                        <th scope="col" className="num">
                          Avg answer
                        </th>
                        <th scope="col">
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...sessions].reverse().map((s) => (
                        <tr key={s.id}>
                          <td>{fmtDateTime(s.started_at)}</td>
                          <td>{fmtLen(s)}</td>
                          <td className="num strong">
                            {s.overall_score != null ? s.overall_score.toFixed(1) : s.report_status === 'pending' ? '…' : '–'}
                            {s.partial && (
                              <span className="chip" title="Too few answers to count in trends">
                                partial
                              </span>
                            )}
                          </td>
                          {CRITERIA.map((c) => (
                            <td key={c.key} className="num">
                              {s.criteria ? s.criteria[c.key].toFixed(1) : '–'}
                            </td>
                          ))}
                          <td className="num">{s.filler_count ?? '–'}</td>
                          <td className="num">{s.avg_answer_seconds != null ? `${Math.round(s.avg_answer_seconds)} s` : '–'}</td>
                          <td className="row-actions">
                            <a href={`#/review/${s.id}`}>Review</a>
                            <button className="ghost small" onClick={() => void deleteSession(s)} aria-label="Delete session">
                              Delete
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </details>
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}

/** Median pitch range, trailing-off share and eye contact per counted session; a dash where there is no data. */
function DeliveryTable({ sessions }: { sessions: HistorySession[] }) {
  if (!sessions.some((s) => s.delivery_trend && Object.values(s.delivery_trend).some((v) => v != null))) return null
  const cell = (v: number | null | undefined, unit: string, nd = 1) => (v != null ? `${v.toFixed(nd)}${unit}` : '–')
  return (
    <details className="disclosure plain">
      <summary>
        <h3>Delivery over time</h3>
        <span className="summary-meta muted small">median per session</span>
        <Chevron />
      </summary>
      <div className="table-wrap">
        <table className="sessions">
          <caption className="sr-only">Delivery over time</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col" className="num">
                Pitch range
              </th>
              <th scope="col" className="num">
                Trailing off
              </th>
              <th scope="col" className="num">
                Eye contact
              </th>
            </tr>
          </thead>
          <tbody>
            {[...sessions].reverse().map((s) => (
              <tr key={s.id}>
                <td>{fmtDateTime(s.started_at)}</td>
                <td className="num">{cell(s.delivery_trend?.pitch_range_st, ' st')}</td>
                <td className="num">{cell(s.delivery_trend?.trail_off_pct, '%', 0)}</td>
                <td className="num">{cell(s.delivery_trend?.on_screen_pct, '%', 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="n">{value}</div>
      <div className="muted small">{label}</div>
    </div>
  )
}

/** Overall score per session (1-5), oldest to newest, with a hover tooltip. */
function ScoreChart({ sessions }: { sessions: HistorySession[] }) {
  const [hover, setHover] = useState<number | null>(null)
  const [mode, setMode] = useState<'overall' | 'type'>('overall')
  // Draw at the container's real pixel width so text and marks keep their size.
  const box = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(640)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const H = 180
  const pad = { l: 30, r: 40, t: 14, b: 26 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const x = (i: number) => pad.l + (sessions.length === 1 ? iw / 2 : (i / (sessions.length - 1)) * iw)
  const y = (v: number) => pad.t + ((5 - v) / 4) * ih
  const pts = sessions.map((s, i) => ({ s, cx: x(i), cy: y(s.overall_score!) }))
  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.cx.toFixed(1)},${p.cy.toFixed(1)}`).join(' ')
  const last = pts[pts.length - 1]
  const h = hover != null ? pts[hover] : null
  // Show at most ~6 labels so they don't collide; same-day sessions are told apart by time.
  const every = Math.max(1, Math.ceil(sessions.length / Math.max(2, Math.floor(iw / 90))))
  const sameDay = new Set(sessions.map((s) => fmtDate(s.started_at))).size < sessions.length
  const tick = (ms: number) =>
    sameDay ? new Date(ms).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : fmtDate(ms)

  // One line per question type: partial sessions are left out, as in the overall trend.
  const counted = sessions.filter((s) => !s.partial)
  const types = typeStats(counted)
  const tx = (s: HistorySession) => {
    const i = sessions.indexOf(s)
    return x(i)
  }

  return (
    <figure className="chart">
      <figcaption className="muted small">
        {mode === 'overall' ? 'Overall score per session (1–5)' : 'Average score per question type (1–5)'}
      </figcaption>
      {types.length > 0 && (
        <div className="chart-toggle" role="group" aria-label="Chart lines">
          <button className={`ghost ${mode === 'overall' ? 'on' : ''}`} aria-pressed={mode === 'overall'} onClick={() => setMode('overall')}>
            Overall
          </button>
          <button className={`ghost ${mode === 'type' ? 'on' : ''}`} aria-pressed={mode === 'type'} onClick={() => setMode('type')}>
            By question type
          </button>
        </div>
      )}
      <div className="chart-box" ref={box}>
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`Overall score over ${sessions.length} sessions, latest ${last.s.overall_score!.toFixed(1)}`}>
          {[1, 2, 3, 4, 5].map((v) => (
            <g key={v}>
              <line className="grid" x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} />
              <text className="axis" x={pad.l - 8} y={y(v)} dy="0.35em" textAnchor="end">
                {v}
              </text>
            </g>
          ))}
          {pts.map((p, i) =>
            i % every === 0 || i === pts.length - 1 ? (
              <text
                key={i}
                className="axis"
                x={p.cx}
                y={H - 6}
                textAnchor={i === 0 ? 'start' : i === pts.length - 1 ? 'end' : 'middle'}
              >
                {tick(p.s.started_at)}
              </text>
            ) : null,
          )}
          {mode === 'type' &&
            types.map((t, ti) => {
              const color = TYPE_COLORS[ti % TYPE_COLORS.length]
              const tp = t.points.map((p) => ({ cx: tx(p.s), cy: y(p.value), ...p }))
              const lastP = tp[tp.length - 1]
              return (
                <g key={t.category}>
                  <path className="type-line" stroke={color} d={tp.map((p, i) => `${i ? 'L' : 'M'}${p.cx.toFixed(1)},${p.cy.toFixed(1)}`).join(' ')} />
                  {tp.map((p, i) => (
                    <circle key={i} className="type-dot" fill={color} cx={p.cx} cy={p.cy} r={4}>
                      <title>{`${CATEGORY_LABEL[t.category] ?? t.category}, ${fmtDateTime(p.s.started_at)}: ${p.value.toFixed(1)}`}</title>
                    </circle>
                  ))}
                  <text className="type-label" fill={color} x={lastP.cx + 9} y={lastP.cy} dy="0.35em">
                    {CATEGORY_LABEL[t.category] ?? t.category}
                  </text>
                </g>
              )
            })}
          {mode === 'overall' && h && <line className="crosshair" x1={h.cx} x2={h.cx} y1={pad.t} y2={pad.t + ih} />}
          {mode === 'overall' && <path className="series" d={path} />}
          {mode === 'overall' && pts.map((p, i) => (
            <circle key={i} className={`dot ${hover === i ? 'on' : ''} ${p.s.partial ? 'partial' : ''}`} cx={p.cx} cy={p.cy} r={hover === i ? 5.5 : 4} />
          ))}
          {mode === 'overall' && (
            <text className="direct-label" x={last.cx + 9} y={last.cy} dy="0.35em">
              {last.s.overall_score!.toFixed(1)}
            </text>
          )}
          {/* Hit targets bigger than the marks. */}
          {mode === 'overall' && pts.map((p, i) => (
            <circle
              key={`hit-${i}`}
              className="hit"
              cx={p.cx}
              cy={p.cy}
              r={14}
              tabIndex={0}
              aria-label={`${fmtDateTime(p.s.started_at)}: ${p.s.overall_score!.toFixed(1)}`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onClick={() => (window.location.hash = `#/review/${p.s.id}`)}
            />
          ))}
        </svg>
        {mode === 'overall' && h && (
          <div
            className="tooltip"
            style={{ left: `${(h.cx / W) * 100}%`, top: `${(h.cy / H) * 100}%` }}
            role="status"
          >
            <div className="muted small">{fmtDateTime(h.s.started_at)}</div>
            <div>
              <strong>{h.s.overall_score!.toFixed(1)}</strong> overall{h.s.partial ? ' (partial, not counted)' : ''}
            </div>
            {h.s.criteria && (
              <div className="small">
                {CRITERIA.map((c) => `${c.label} ${h.s.criteria![c.key].toFixed(1)}`).join(' · ')}
              </div>
            )}
          </div>
        )}
      </div>
    </figure>
  )
}
