import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'

export interface DropdownOption<T extends string | number> {
  value: T
  label: string
  /** Secondary text shown under the label in the open list. */
  hint?: string
}

interface Props<T extends string | number> {
  value: T
  options: DropdownOption<T>[]
  onChange: (value: T) => void
  /** Accessible name when there's no visible <label> around it. */
  ariaLabel?: string
  /** Open upwards; 'auto' flips when there's no room below. */
  placement?: 'auto' | 'up' | 'down'
  size?: 'md' | 'sm'
  disabled?: boolean
  className?: string
}

/** A keyboard-accessible listbox styled to match the app (replaces native <select>). */
export default function Dropdown<T extends string | number>({
  value,
  options,
  onChange,
  ariaLabel,
  placement = 'auto',
  size = 'md',
  disabled,
  className = '',
}: Props<T>) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [up, setUp] = useState(placement === 'up')
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const id = useId()
  const selected = options.findIndex((o) => o.value === value)
  const current = options[selected]

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  useLayoutEffect(() => {
    if (!open) return
    if (placement === 'auto' && button.current && list.current) {
      const b = button.current.getBoundingClientRect()
      const h = list.current.offsetHeight
      setUp(b.bottom + h + 8 > window.innerHeight && b.top - h - 8 > 0)
    }
    list.current?.querySelector<HTMLElement>(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, active, placement])

  const show = () => {
    setActive(Math.max(0, selected))
    setOpen(true)
  }
  const pick = (i: number) => {
    onChange(options[i].value)
    setOpen(false)
    button.current?.focus()
  }

  const onKey = (e: KeyboardEvent) => {
    if (disabled) return
    const last = options.length - 1
    let handled = true
    switch (e.key) {
      case 'ArrowDown':
        if (open) setActive((a) => Math.min(last, a + 1))
        else show()
        break
      case 'ArrowUp':
        if (open) setActive((a) => Math.max(0, a - 1))
        else show()
        break
      case 'Home':
        if (open) setActive(0)
        else handled = false
        break
      case 'End':
        if (open) setActive(last)
        else handled = false
        break
      case 'Enter':
      case ' ':
        if (open) pick(active)
        else show()
        break
      case 'Escape':
        if (open) setOpen(false)
        else handled = false
        break
      case 'Tab':
        setOpen(false)
        handled = false
        break
      default: {
        // Type-ahead: jump to the first option starting with that letter.
        if (e.key.length === 1 && /\S/.test(e.key)) {
          const k = e.key.toLowerCase()
          const from = open ? active : selected
          const order = options.map((_, i) => (from + 1 + i) % options.length)
          const hit = order.find((i) => options[i].label.toLowerCase().startsWith(k))
          if (hit != null) {
            if (open) setActive(hit)
            else onChange(options[hit].value)
          }
        } else handled = false
      }
    }
    if (handled) {
      e.preventDefault()
      e.stopPropagation()
    }
  }

  return (
    <div ref={root} className={`dropdown ${size} ${open ? 'open' : ''} ${up ? 'up' : ''} ${className}`}>
      <button
        ref={button}
        type="button"
        className="dropdown-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-label={ariaLabel}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onKey}
      >
        <span className="dropdown-value">{current?.label ?? '—'}</span>
        <Chevron />
      </button>
      <ul ref={list} id={`${id}-list`} role="listbox" className="dropdown-list" hidden={!open} tabIndex={-1}>
        {options.map((o, i) => (
          <li
            key={String(o.value)}
            id={`${id}-${i}`}
            data-i={i}
            role="option"
            aria-selected={i === selected}
            className={`${i === active ? 'active' : ''} ${i === selected ? 'selected' : ''}`}
            onPointerEnter={() => setActive(i)}
            onPointerDown={(e) => e.preventDefault()}
            onClick={() => pick(i)}
          >
            <span>
              {o.label}
              {o.hint && <span className="dropdown-hint">{o.hint}</span>}
            </span>
            {i === selected && (
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
                <path d="m2.5 6.2 2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Down chevron used by dropdowns and collapsible sections; CSS rotates it when open. */
export function Chevron() {
  return (
    <svg className="chevron" width="14" height="14" viewBox="0 0 12 12" aria-hidden>
      <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
