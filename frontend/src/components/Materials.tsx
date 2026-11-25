import { useState, type ChangeEvent } from 'react'
import { api, MAX_PACK_CHARS, type MaterialInput, type MaterialKind, type MaterialSource } from '../api'
import Dropdown, { Chevron, type DropdownOption } from './Dropdown'

/** A row in the editor: a material, or a file that failed to load (error, no text; never saved). */
export interface MaterialRow extends MaterialInput {
  key: string
  synthetic?: boolean
  error?: string
}

export const KIND_OPTIONS: DropdownOption<MaterialKind>[] = [
  { value: 'job', label: 'Job', hint: 'Job advert or description' },
  { value: 'candidate', label: 'About you', hint: 'CV, portfolio, cover letter' },
  { value: 'organisation', label: 'Organisation', hint: 'Company notes, research' },
  { value: 'format', label: 'Format', hint: 'Mark scheme, person spec, stations' },
  { value: 'other', label: 'Other' },
]
const SOURCE_LABEL: Record<MaterialSource, string> = { paste: 'pasted', pdf: 'PDF', text_file: 'text file', research: 'web research' }

// Same rules as backend/materials.py guess_kind.
const KIND_RULES: [MaterialKind, RegExp][] = [
  ['candidate', /\bcv\b|resum|curriculum|cover.?letter|portfolio|my.?profile|linkedin/],
  ['format', /mark.?scheme|marking|person.?spec|station|format|rubric|criteria|assessment|selection/],
  ['organisation', /company|organi[sz]ation|about.?us|annual.?report|values|mission|research|company.?notes/],
  ['job', /\bjd\b|job|advert|vacancy|posting|role|description|spec/],
]

export function guessKind(name: string): MaterialKind {
  const n = name.toLowerCase().replace(/[_\-.]+/g, ' ')
  return KIND_RULES.find(([, re]) => re.test(n))?.[0] ?? 'other'
}

let nextKey = 0
export const newKey = () => `m${++nextKey}`

export const totalChars = (rows: MaterialRow[]) => rows.reduce((n, r) => n + r.text.length, 0)

/** The rows that get saved: those with text. */
export const toSave = (rows: MaterialRow[]): MaterialInput[] =>
  rows.filter((r) => r.text.trim()).map(({ name, kind, source, text }) => ({ name: name.trim() || 'Notes', kind, source, text }))

function displayName(file: string) {
  const base = file.replace(/\.(pdf|txt|md)$/i, '').replace(/[_-]+/g, ' ').trim()
  return (base || file).slice(0, 80)
}

interface Props {
  rows: MaterialRow[]
  onChange: (rows: MaterialRow[]) => void
  company: string
  role: string
  onError: (message: string | null) => void
}

export default function Materials({ rows, onChange, company, role, onError }: Props) {
  const [loading, setLoading] = useState(false)
  const [researching, setResearching] = useState(false)
  const total = totalChars(rows)

  const update = (key: string, patch: Partial<MaterialRow>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const remove = (key: string) => onChange(rows.filter((r) => r.key !== key))

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (!files.length) return
    onError(null)
    setLoading(true)
    try {
      const results = await api.extractText(files)
      const added: MaterialRow[] = results.map((r) => {
        const name = displayName(r.name)
        const source: MaterialSource = r.name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'text_file'
        return 'error' in r
          ? { key: newKey(), name, kind: guessKind(r.name), source, text: '', error: `${r.name}: ${r.error}` }
          : { key: newKey(), name, kind: guessKind(r.name), source, text: r.text }
      })
      onChange([...rows, ...added])
    } catch (err) {
      onError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const paste = () => onChange([...rows, { key: newKey(), name: 'Notes', kind: 'other', source: 'paste', text: '' }])

  const research = async () => {
    if (!window.confirm(`Draft notes on ${company} from the web? This spends 1 Claude request and uses web search. The draft is added as a material for you to check and edit.`)) return
    onError(null)
    setResearching(true)
    try {
      const jobText = rows.filter((r) => r.kind === 'job').map((r) => r.text).join('\n\n').slice(0, 50000)
      const r = await api.research(company, role, jobText)
      const text = r.sources.length ? `${r.notes}\n\nSources:\n${r.sources.map((u) => `- ${u}`).join('\n')}` : r.notes
      onChange([...rows, { key: newKey(), name: `Web research: ${company}`.slice(0, 80), kind: 'organisation', source: 'research', text }])
    } catch (err) {
      onError((err as Error).message)
    } finally {
      setResearching(false)
    }
  }

  return (
    <div className="materials">
      {rows.length === 0 && (
        <p className="muted small empty">
          Add what you have: the job advert, your CV, company notes, a mark scheme or person specification, the interview format.
        </p>
      )}
      <ul className="material-list">
        {rows.map((r) => (
          <li key={r.key} className={`material ${r.error ? 'failed' : ''}`}>
            <div className="material-head">
              <input
                className="material-name"
                aria-label="Material name"
                value={r.name}
                maxLength={80}
                onChange={(e) => update(r.key, { name: e.target.value })}
              />
              <div className="field material-kind">
                <Dropdown ariaLabel="Kind" size="sm" value={r.kind} options={KIND_OPTIONS} onChange={(v) => update(r.key, { kind: v })} />
              </div>
              <span className="muted small material-meta">
                {SOURCE_LABEL[r.source]} · {r.text.length.toLocaleString()} chars
              </span>
              <button type="button" className="small ghost" onClick={() => remove(r.key)}>
                Remove
              </button>
            </div>
            {r.error ? (
              <div className="banner error">{r.error}</div>
            ) : (
              <details className="disclosure material-text" open={!r.text || undefined}>
                <summary>
                  <span className="small">{r.synthetic ? 'Read and edit (from this pack’s original fields)' : 'Read and edit the text'}</span>
                  <Chevron />
                </summary>
                <textarea
                  aria-label={`${r.name} text`}
                  rows={8}
                  value={r.text}
                  onChange={(e) => update(r.key, { text: e.target.value })}
                  placeholder="Paste the text here"
                />
              </details>
            )}
          </li>
        ))}
      </ul>
      <div className="material-actions">
        <label className="file-button">
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
            <path d="M8 11V2.5M4.5 6 8 2.5 11.5 6M2.5 10.5v2a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1v-2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {loading ? 'Reading…' : 'Upload files'}
          <input type="file" accept=".pdf,.txt,.md" multiple onChange={upload} disabled={loading} />
        </label>
        <button type="button" className="small" onClick={paste}>
          Paste text
        </button>
        <button type="button" className="small" disabled={!company.trim() || researching} onClick={research}>
          {researching ? 'Searching the web (up to about a minute)…' : 'Draft from the web'}
        </button>
        <span className={`small material-total ${total > MAX_PACK_CHARS ? 'over' : 'muted'}`}>
          {total.toLocaleString()} / {MAX_PACK_CHARS.toLocaleString()} characters
        </span>
      </div>
      <p className="muted small">
        PDF, .txt or .md, several at once. {company.trim() ? 'Draft from the web: 1 Claude request, uses web search.' : 'Enter the company above to draft notes from the web (1 Claude request).'}
      </p>
    </div>
  )
}
