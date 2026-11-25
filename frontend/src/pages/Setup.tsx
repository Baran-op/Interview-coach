import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { api, type Pack, type PackInput, type SessionListItem } from '../api'
import { getRecordMode, setRecordMode, type RecordMode } from '../audio/recorder'

const EMPTY: PackInput = {
  title: '',
  role: '',
  company: '',
  jd: '',
  profile: '',
  company_notes: '',
  options: {
    interview_type: 'mixed',
    stage: 'full',
    num_questions: 5,
    minutes: null,
    difficulty: 'medium',
    style: 'neutral',
    interviewer_name: 'Alex',
    voice: 'af_heart',
  },
}

// Kokoro voice ids: a/b = US/UK English, f/m = female/male.
function voiceLabel(id: string) {
  const [prefix, name] = id.split('_')
  const accent = prefix?.[0] === 'b' ? 'UK' : 'US'
  const gender = prefix?.[1] === 'm' ? 'male' : 'female'
  return `${name ? name[0].toUpperCase() + name.slice(1) : id} (${accent} ${gender})`
}

export function packSummary(p: Pack) {
  const o = p.options
  const length = o.minutes ? `${o.minutes} min` : `${o.num_questions} questions`
  return `${o.stage ?? 'full'} · ${o.interview_type} · ${length} · ${o.difficulty} · ${o.style}`
}

interface Props {
  onStart: (pack: Pack) => void
  /** Open this pack for editing (#/edit/<id>). */
  editPackId?: string
}

export default function Setup({ onStart, editPackId }: Props) {
  const [packs, setPacks] = useState<Pack[]>([])
  const [form, setForm] = useState<PackInput>(EMPTY)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [researching, setResearching] = useState(false)
  const [sources, setSources] = useState<string[]>([])
  const [voices, setVoices] = useState<string[]>(['af_heart'])
  const [recordMode, setMode] = useState<RecordMode>(getRecordMode)
  const [sessions, setSessions] = useState<SessionListItem[]>([])

  useEffect(() => {
    api
      .listSessions(8)
      .then(setSessions)
      .catch(() => {})
    api
      .voices()
      .then((v) => setVoices(v.voices))
      .catch(() => {})
    api
      .listPacks()
      .then((list) => {
        setPacks(list)
        // The CV is saved once and reused: prefill it from the latest pack.
        if (list.length > 0) setForm((f) => ({ ...f, profile: f.profile || list[0].profile }))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (editPackId) api.getPack(editPackId).then(editPack, (e: Error) => setError(e.message))
  }, [editPackId])

  const set = <K extends keyof PackInput>(key: K, value: PackInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))
  const setOpt = <K extends keyof PackInput['options']>(key: K, value: PackInput['options'][K]) =>
    setForm((f) => ({ ...f, options: { ...f.options, [key]: value } }))

  const loadFile = async (e: ChangeEvent<HTMLInputElement>, key: 'jd' | 'profile') => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    try {
      const isPdf = file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf'
      set(key, isPdf ? await api.extractPdfText(file) : await file.text())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const draftNotes = async () => {
    if (form.company_notes.trim() && !window.confirm('Replace the current company notes with a draft from the web?')) return
    setError(null)
    setResearching(true)
    try {
      const r = await api.research(form.company, form.role, form.jd)
      set('company_notes', r.notes)
      setSources(r.sources)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setResearching(false)
    }
  }

  const editPack = (p: Pack) => {
    setEditingId(p.id)
    setForm({
      title: p.title,
      role: p.role,
      company: p.company,
      jd: p.jd,
      profile: p.profile,
      company_notes: p.company_notes,
      options: { ...EMPTY.options, ...p.options },
    })
    window.scrollTo({ top: 0 })
  }

  const stopEditing = () => {
    setEditingId(null)
    setForm({ ...EMPTY, profile: form.profile })
    if (window.location.hash.startsWith('#/edit/')) window.history.replaceState(null, '', '#/')
  }

  const save = async (asNew: boolean) => {
    setError(null)
    setSaving(true)
    try {
      const title = form.title.trim() || [form.role, form.company].filter(Boolean).join(' @ ') || 'Untitled'
      const data = { ...form, title }
      const pack = editingId && !asNew ? await api.updatePack(editingId, data) : await api.createPack(data)
      onStart(pack)
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void save(false)
  }

  return (
    <div className="setup">
      <form className="card" onSubmit={submit}>
        <h2>
          {editingId ? 'Edit pack' : 'New interview'}
          {editingId && (
            <button type="button" className="ghost small" onClick={stopEditing}>
              Cancel editing
            </button>
          )}
        </h2>

        <div className="row">
          <label>
            Role
            <input value={form.role} onChange={(e) => set('role', e.target.value)} placeholder="Solutions Engineer" />
          </label>
          <label>
            Company
            <input value={form.company} onChange={(e) => set('company', e.target.value)} placeholder="Contoso" />
          </label>
          <label>
            Pack name
            <input value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="(role @ company)" />
          </label>
        </div>

        <label>
          <span className="label-row">
            Job description
            <input type="file" accept=".txt,.md,.pdf" onChange={(e) => loadFile(e, 'jd')} />
          </span>
          <textarea required rows={10} value={form.jd} onChange={(e) => set('jd', e.target.value)} placeholder="Paste the full job description" />
        </label>

        <label>
          <span className="label-row">
            My profile / CV
            <input type="file" accept=".txt,.md,.pdf" onChange={(e) => loadFile(e, 'profile')} />
          </span>
          <textarea rows={8} value={form.profile} onChange={(e) => set('profile', e.target.value)} placeholder="Paste your CV text (reused for future packs)" />
        </label>

        <label>
          <span className="label-row">
            Company notes
            <button type="button" className="ghost small" disabled={!form.company.trim() || researching} onClick={draftNotes}>
              {researching ? 'Searching the web (up to about a minute)...' : 'Draft from the web'}
            </button>
          </span>
          <textarea rows={4} value={form.company_notes} onChange={(e) => set('company_notes', e.target.value)} placeholder="Mission, products, recent news, values" />
        </label>
        <p className="hint">
          "Draft from the web" uses your Claude usage (one request with web search). The draft is only filled in here: check it, edit it, and it is saved with the pack.
        </p>
        {sources.length > 0 && (
          <div className="hint">
            Sources:
            <ul>
              {sources.map((u) => (
                <li key={u}>
                  <a href={u} target="_blank" rel="noreferrer">{u}</a>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="row">
          <label>
            Type
            <select value={form.options.interview_type} onChange={(e) => setOpt('interview_type', e.target.value as PackInput['options']['interview_type'])}>
              <option value="behavioural">Behavioural</option>
              <option value="technical">Technical</option>
              <option value="mixed">Mixed</option>
              <option value="case">Case</option>
              <option value="roleplay">Role-play</option>
            </select>
          </label>
          <label>
            Stage
            <select value={form.options.stage} onChange={(e) => setOpt('stage', e.target.value as PackInput['options']['stage'])}>
              <option value="screen">Screening call</option>
              <option value="full">Full interview</option>
              <option value="final">Final round</option>
            </select>
          </label>
          <label>
            Length
            <span className="length">
              <select
                value={form.options.minutes ? 'minutes' : 'questions'}
                onChange={(e) => setOpt('minutes', e.target.value === 'minutes' ? 20 : null)}
              >
                <option value="questions">Questions</option>
                <option value="minutes">Minutes</option>
              </select>
              {form.options.minutes ? (
                <input type="number" min={5} max={120} step={5} value={form.options.minutes} onChange={(e) => setOpt('minutes', Number(e.target.value))} />
              ) : (
                <input type="number" min={1} max={20} value={form.options.num_questions} onChange={(e) => setOpt('num_questions', Number(e.target.value))} />
              )}
            </span>
          </label>
          <label>
            Difficulty
            <select value={form.options.difficulty} onChange={(e) => setOpt('difficulty', e.target.value as PackInput['options']['difficulty'])}>
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </label>
          <label>
            Style
            <select value={form.options.style} onChange={(e) => setOpt('style', e.target.value as PackInput['options']['style'])}>
              <option value="friendly">Friendly</option>
              <option value="neutral">Neutral</option>
              <option value="tough">Tough</option>
            </select>
          </label>
          <label>
            Interviewer
            <input value={form.options.interviewer_name} onChange={(e) => setOpt('interviewer_name', e.target.value)} />
          </label>
          <label>
            Voice
            <select value={form.options.voice} onChange={(e) => setOpt('voice', e.target.value)}>
              {voices.map((v) => (
                <option key={v} value={v}>
                  {voiceLabel(v)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="inline">
          Record the session
          <select
            value={recordMode}
            onChange={(e) => {
              const m = e.target.value as RecordMode
              setMode(m)
              setRecordMode(m)
            }}
          >
            <option value="webcam">Webcam + audio</option>
            <option value="avatar">Avatar + audio</option>
            <option value="both">Avatar and webcam side by side</option>
            <option value="audio">Audio only</option>
            <option value="off">Don't record</option>
          </select>
        </label>

        {error && <div className="banner error">{error}</div>}
        <div className="form-actions">
          <button type="submit" className="primary" disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Save changes & start interview' : 'Save pack & start interview'}
          </button>
          {editingId && (
            <button type="button" disabled={saving} onClick={() => void save(true)}>
              Save as a new pack & start
            </button>
          )}
        </div>
      </form>

      <aside className="card packs">
        <h2>Saved packs</h2>
        {packs.length === 0 && <p className="muted">None yet.</p>}
        {packs.map((p) => (
          <div key={p.id} className="pack">
            <div>
              <strong>{p.title}</strong>
              <div className="muted small">{packSummary(p)}</div>
            </div>
            <div className="pack-actions">
              <button type="button" onClick={() => onStart(p)}>Start</button>
              <a className="button-link" href={`#/drill/${p.id}`}>Drill</a>
              <a className="button-link" href={`#/prep/${p.id}`}>Prep</a>
              <button type="button" className="ghost" onClick={() => editPack(p)}>
                Edit
              </button>
            </div>
          </div>
        ))}
        {sessions.length > 0 && (
          <>
            <h2 className="spaced">
              Recent sessions <a className="small" href="#/history">All history →</a>
            </h2>
            {sessions.map((s) => (
              <a key={s.id} className="session-link" href={`#/review/${s.id}`}>
                <span>
                  <strong>{s.pack_title}</strong>
                  <span className="muted small"> · {new Date(s.started_at).toLocaleString()}</span>
                </span>
                <span className="score-chip">
                  {s.overall_score != null ? s.overall_score.toFixed(1) : s.report_status === 'pending' ? '…' : '–'}
                </span>
              </a>
            ))}
          </>
        )}
      </aside>
    </div>
  )
}
