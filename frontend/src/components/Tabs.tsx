import type { KeyboardEvent } from 'react'

export interface TabDef<K extends string> {
  key: K
  label: string
  /** Tabs are links (the URL hash holds the tab), so the back button and shared links work. */
  href: string
}

/** Ids that tie a tab to its panel. */
export const panelProps = (prefix: string, key: string) => ({ id: `${prefix}-panel-${key}`, role: 'tabpanel', 'aria-labelledby': `${prefix}-tab-${key}` })

/**
 * WAI-ARIA tabs over hash links: only the selected tab is in the Tab order; Left/Right/Home/End move between tabs
 * and select them.
 */
export default function Tabs<K extends string>({ tabs, current, label, idPrefix }: { tabs: TabDef<K>[]; current: K; label: string; idPrefix: string }) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.key === current)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]
    if (next == null) return
    e.preventDefault()
    const t = tabs[(next + tabs.length) % tabs.length]
    window.location.hash = t.href
    requestAnimationFrame(() => document.getElementById(`${idPrefix}-tab-${t.key}`)?.focus())
  }
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((t) => (
        <a
          key={t.key}
          id={`${idPrefix}-tab-${t.key}`}
          role="tab"
          aria-selected={t.key === current}
          aria-controls={`${idPrefix}-panel-${t.key}`}
          tabIndex={t.key === current ? 0 : -1}
          className={`tab ${t.key === current ? 'on' : ''}`}
          href={t.href}
        >
          {t.label}
        </a>
      ))}
    </div>
  )
}
