import { useEffect, useState } from 'react'
import { api, type Pack, type SessionListItem } from '../api'
import Menu from '../components/Menu'
import { PackBadges, packSummary } from '../packInfo'

/** Home: saved packs and recent sessions first; a new pack is one click away. */
export default function Home({ onStart }: { onStart: (pack: Pack) => void }) {
  const [packs, setPacks] = useState<Pack[] | null>(null)
  const [sessions, setSessions] = useState<SessionListItem[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    api.listPacks().then(setPacks, (e: Error) => setError(e.message))
    api
      .listSessions(8)
      .then(setSessions)
      .catch(() => {})
  }
  useEffect(load, [])

  // Same confirmation as History: names the pack and how many sessions go with it.
  const deletePack = async (p: Pack) => {
    setError(null)
    try {
      const n = (await api.packHistory(p.id)).length
      const what = n ? ` and its ${n} session${n > 1 ? 's' : ''} (recordings and reports)` : ''
      if (!window.confirm(`Delete the pack "${p.title}"${what}? This can't be undone.`)) return
      await api.deletePack(p.id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="home">
      <div className="page-head">
        <div>
          <p className="eyebrow">Mock interview</p>
          <h1 className="page-title">Home</h1>
          <p className="muted lede">Rerun a saved pack, look back at a session, or make a new pack from a job advert and your CV.</p>
        </div>
        <a className="button-link primary" href="#/new">
          + New pack
        </a>
      </div>
      {error && <div className="banner error">{error}</div>}

      <div className="home-grid">
        <section className="card">
          <h2 className="side-title">
            Saved packs <span className="count">{packs?.length ?? 0}</span>
          </h2>
          {packs?.length === 0 && (
            <p className="muted small empty">
              No packs yet. <a href="#/new">Make one</a> from the job advert, your CV and anything else you have; it is saved so you can rerun it.
            </p>
          )}
          <div className="pack-list">
            {packs?.map((p) => (
              <div key={p.id} className="pack">
                <div className="pack-info">
                  <strong>{p.title}</strong>
                  <div className="muted small">{packSummary(p)}</div>
                  <PackBadges pack={p} />
                </div>
                <div className="pack-actions">
                  <button type="button" className="small" onClick={() => onStart(p)}>
                    Start
                  </button>
                  <a className="button-link small" href={`#/brief/${p.id}`}>
                    Open
                  </a>
                  <Menu
                    label="⋯"
                    ariaLabel={`More for ${p.title}`}
                    size="sm"
                    items={[
                      { label: 'Interview brief', href: `#/brief/${p.id}` },
                      { label: 'Prep', href: `#/prep/${p.id}` },
                      { label: 'Drill', href: `#/drill/${p.id}` },
                      { label: 'Edit', href: `#/edit/${p.id}` },
                      { label: 'Delete pack', onSelect: () => void deletePack(p), danger: true },
                    ]}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>

        {sessions.length > 0 && (
          <section className="card">
            <h2 className="side-title">
              Recent sessions
              <a className="small subtle-link" href="#/history">
                All history →
              </a>
            </h2>
            <div className="session-list">
              {sessions.map((s) => (
                <a key={s.id} className="session-link" href={`#/review/${s.id}`}>
                  <span className="session-info">
                    <strong>{s.pack_title}</strong>
                    <span className="muted small">
                      {new Date(s.started_at).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </span>
                  <span className="score-chip">{s.overall_score != null ? s.overall_score.toFixed(1) : s.report_status === 'pending' ? '…' : '–'}</span>
                </a>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
