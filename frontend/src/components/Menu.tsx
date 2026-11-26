import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Chevron } from './Dropdown'

export interface MenuItem {
  label: string
  /** A link item (e.g. a download); otherwise `onSelect` runs. */
  href?: string
  download?: boolean
  onSelect?: () => void
  disabled?: boolean
  /** Muted text under the label (why it is disabled, a cost). */
  hint?: string
  /** Destructive (delete): set apart from the other items. */
  danger?: boolean
}

interface Props {
  /** Button content: text, or "⋯" with an `ariaLabel`. */
  label: ReactNode
  ariaLabel?: string
  items: MenuItem[]
  /** Show a chevron after the label. */
  chevron?: boolean
  align?: 'left' | 'right'
  size?: 'md' | 'sm'
  className?: string
}

/**
 * A menu button (WAI-ARIA menu pattern): Enter/Space/ArrowDown opens it on the first item, arrows move,
 * Home/End jump, Escape closes and returns focus, Tab or a click outside closes it.
 */
export default function Menu({ label, ariaLabel, items, chevron, align = 'right', size = 'md', className = '' }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  const entries = () => [...(list.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])]
  const focusAt = (i: number) => {
    const all = entries()
    if (all.length) all[(i + all.length) % all.length].focus()
  }
  const show = (at: 'first' | 'last') => {
    setOpen(true)
    requestAnimationFrame(() => focusAt(at === 'first' ? 0 : -1))
  }
  const close = (refocus = true) => {
    setOpen(false)
    if (refocus) button.current?.focus()
  }

  const onButtonKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      show('first')
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      show('last')
    }
  }
  const onListKey = (e: KeyboardEvent) => {
    const all = entries()
    const i = all.indexOf(document.activeElement as HTMLElement)
    switch (e.key) {
      case 'ArrowDown':
        focusAt(i + 1)
        break
      case 'ArrowUp':
        focusAt(i - 1)
        break
      case 'Home':
        focusAt(0)
        break
      case 'End':
        focusAt(-1)
        break
      case 'Escape':
        close()
        break
      case 'Tab':
        setOpen(false)
        return
      default:
        return
    }
    e.preventDefault()
  }

  const pick = (item: MenuItem) => {
    if (item.disabled) return
    close()
    item.onSelect?.()
  }

  return (
    <div ref={root} className={`menu ${open ? 'open' : ''} ${className}`.trim()}>
      <button
        ref={button}
        type="button"
        className={size === 'sm' ? 'small' : ''}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        aria-label={ariaLabel}
        onClick={() => (open ? close(false) : show('first'))}
        onKeyDown={onButtonKey}
      >
        {label}
        {chevron && <Chevron />}
      </button>
      <div ref={list} id={id} role="menu" aria-label={ariaLabel ?? (typeof label === 'string' ? label : undefined)} className={`menu-list ${align}`} hidden={!open} onKeyDown={onListKey}>
        {items.map((item) =>
          item.href && !item.disabled ? (
            <a key={item.label} role="menuitem" tabIndex={-1} href={item.href} download={item.download || undefined} onClick={() => pick(item)}>
              <span>{item.label}</span>
              {item.hint && <span className="menu-hint">{item.hint}</span>}
            </a>
          ) : (
            <button key={item.label} type="button" role="menuitem" tabIndex={-1} className={item.danger ? 'menu-danger' : undefined} aria-disabled={item.disabled || undefined} onClick={() => pick(item)}>
              <span>{item.label}</span>
              {item.hint && <span className="menu-hint">{item.hint}</span>}
            </button>
          ),
        )}
      </div>
    </div>
  )
}
