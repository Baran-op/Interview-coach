import { useEffect, useRef, useState } from 'react'
import { api, type Criterion, type HistorySession, type Pack, type PackHistory } from '../api'
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
      <h1 className="page-title">History</h1>
      {error && <div className="banner error">{error}</div>}
      {data.length === 0 && (
        <div className="card">
          <p className="muted">
            No interview packs yet. <a href="#/">Create one</a> to get started.
          </p>
        </div>
      )}
      {data.map(({ pack, sessions }) => {
        const scored = sessions.filter((s) => s.overall_score != null)
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
                {scored.length > 1 && <ScoreChart sessions={scored} />}
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
              </>
            )}
          </section>
        )
      })}
    </div>
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

  return (
    <figure className="chart">
      <figcaption className="muted small">Overall score per session (1–5)</figcaption>
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
          {h && <line className="crosshair" x1={h.cx} x2={h.cx} y1={pad.t} y2={pad.t + ih} />}
          <path className="series" d={path} />
          {pts.map((p, i) => (
            <circle key={i} className={`dot ${hover === i ? 'on' : ''}`} cx={p.cx} cy={p.cy} r={hover === i ? 5.5 : 4} />
          ))}
          <text className="direct-label" x={last.cx + 9} y={last.cy} dy="0.35em">
            {last.s.overall_score!.toFixed(1)}
          </text>
          {/* Hit targets bigger than the marks. */}
          {pts.map((p, i) => (
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
        {h && (
          <div
            className="tooltip"
            style={{ left: `${(h.cx / W) * 100}%`, top: `${(h.cy / H) * 100}%` }}
            role="status"
          >
            <div className="muted small">{fmtDateTime(h.s.started_at)}</div>
            <div>
              <strong>{h.s.overall_score!.toFixed(1)}</strong> overall
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
