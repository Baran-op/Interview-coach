import { useEffect, useState } from 'react'
import { api, type Pack } from '../api'
import { PackBadges, packSummary } from '../packInfo'

export type PackTab = 'materials' | 'brief' | 'prep' | 'drill'

const TABS: { key: PackTab; label: string; href: (id: string) => string }[] = [
  { key: 'materials', label: 'Materials', href: (id) => `#/edit/${id}` },
  { key: 'brief', label: 'Brief', href: (id) => `#/brief/${id}` },
  { key: 'prep', label: 'Prep', href: (id) => `#/prep/${id}` },
  { key: 'drill', label: 'Drill', href: (id) => `#/drill/${id}` },
]

interface Props {
  packId: string
  tab: PackTab
  onStart: (pack: Pack) => void
  /** The screen's one primary button; false where the page has its own main action. */
  primary?: boolean
  disabled?: boolean
  /** Return false to cancel the start (e.g. unsaved edits the person wants to keep). */
  confirmStart?: () => boolean
  /** Change it to reload the pack (title, badges) after a save. */
  version?: unknown
}

/** Shared header for a pack's pages: title, format, badges, tabs Materials | Brief | Prep | Drill and Start. */
export default function PackHeader({ packId, tab, onStart, primary = true, disabled, confirmStart, version }: Props) {
  const [pack, setPack] = useState<Pack | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getPack(packId).then(setPack, (e: Error) => setError(e.message))
  }, [packId, version])

  const start = () => {
    if (confirmStart && !confirmStart()) return
    // A fresh copy: its brief_meta (format, minutes) drives the interview timer.
    api.getPack(packId).then(onStart, (e: Error) => setError(e.message))
  }

  return (
    <header className="pack-header">
      <div className="pack-header-top">
        <div className="pack-header-info">
          <p className="eyebrow">Interview pack</p>
          <h1 className="page-title">{pack?.title ?? ' '}</h1>
          {pack && (
            <div className="pack-meta">
              <span className="muted small">{packSummary(pack)}</span>
              <PackBadges pack={pack} />
            </div>
          )}
        </div>
        <button type="button" className={primary ? 'primary' : ''} disabled={disabled} onClick={start}>
          Start interview
        </button>
      </div>
      <nav className="tabs pack-tabs" aria-label="Pack sections">
        {TABS.map((t) => (
          <a key={t.key} className={`tab ${t.key === tab ? 'on' : ''}`} aria-current={t.key === tab ? 'page' : undefined} href={t.href(packId)}>
            {t.label}
          </a>
        ))}
      </nav>
      {error && <div className="banner error">{error}</div>}
    </header>
  )
}
