import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import { api, type Pack, type PackInput } from '../api'

const EMPTY: PackInput = {
  title: '',
  role: '',
  company: '',
  jd: '',
  profile: '',
  company_notes: '',
  options: {
    interview_type: 'mixed',
    num_questions: 5,
    minutes: null,
    difficulty: 'medium',
    style: 'neutral',
    interviewer_name: 'Alex',
  },
}

interface Props {
  onStart: (pack: Pack) => void
}

export default function Setup({ onStart }: Props) {
  const [packs, setPacks] = useState<Pack[]>([])
  const [form, setForm] = useState<PackInput>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .listPacks()
      .then((list) => {
        setPacks(list)
        // The CV is saved once and reused: prefill it from the latest pack.
        if (list.length > 0) setForm((f) => ({ ...f, profile: f.profile || list[0].profile }))
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const set = <K extends keyof PackInput>(key: K, value: PackInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))
  const setOpt = <K extends keyof PackInput['options']>(key: K, value: PackInput['options'][K]) =>
    setForm((f) => ({ ...f, options: { ...f.options, [key]: value } }))

  const loadFile = async (e: ChangeEvent<HTMLInputElement>, key: 'jd' | 'profile') => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.name.toLowerCase().endsWith('.pdf')) {
      setError('PDF upload is not supported yet: paste the text for now.')
      return
    }
    set(key, await file.text())
  }

  const editPack = (p: Pack) => {
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

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const title = form.title.trim() || [form.role, form.company].filter(Boolean).join(' @ ') || 'Untitled'
      const pack = await api.createPack({ ...form, title })
      onStart(pack)
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <div className="setup">
      <form className="card" onSubmit={submit}>
        <h2>New interview</h2>

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
          Company notes
          <textarea rows={4} value={form.company_notes} onChange={(e) => set('company_notes', e.target.value)} placeholder="Mission, products, recent news, values" />
        </label>

        <div className="row">
          <label>
            Type
            <select value={form.options.interview_type} onChange={(e) => setOpt('interview_type', e.target.value as PackInput['options']['interview_type'])}>
              <option value="behavioural">Behavioural</option>
              <option value="technical">Technical</option>
              <option value="mixed">Mixed</option>
              <option value="case">Case</option>
            </select>
          </label>
          <label>
            Questions
            <input type="number" min={1} max={20} value={form.options.num_questions} onChange={(e) => setOpt('num_questions', Number(e.target.value))} />
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
        </div>

        {error && <div className="banner error">{error}</div>}
        <button type="submit" className="primary" disabled={saving}>
          {saving ? 'Saving…' : 'Save pack & start interview'}
        </button>
      </form>

      <aside className="card packs">
        <h2>Saved packs</h2>
        {packs.length === 0 && <p className="muted">None yet.</p>}
        {packs.map((p) => (
          <div key={p.id} className="pack">
            <div>
              <strong>{p.title}</strong>
              <div className="muted small">
                {p.options.interview_type} · {p.options.num_questions} questions · {p.options.difficulty} · {p.options.style}
              </div>
            </div>
            <div className="pack-actions">
              <button type="button" onClick={() => onStart(p)}>Start</button>
              <button type="button" className="ghost" onClick={() => editPack(p)}>Copy to form</button>
            </div>
          </div>
        ))}
      </aside>
    </div>
  )
}
