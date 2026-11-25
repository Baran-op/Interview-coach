import { useEffect, useState, type FormEvent } from 'react'
import { api, MAX_PACK_CHARS, type BriefMeta, type Material, type Pack, type PackInput, type SessionListItem } from '../api'
import { getRecordMode, setRecordMode, type RecordMode } from '../audio/recorder'
import { faceModelAvailable, getFaceTracking, setFaceTracking } from '../face/FaceTracker'

import Dropdown, { Chevron, type DropdownOption } from '../components/Dropdown'
import Materials, { newKey, toSave, totalChars, type MaterialRow } from '../components/Materials'

type Opts = PackInput['options']
const TYPE_OPTIONS: DropdownOption<Opts['interview_type']>[] = [
  { value: 'behavioural', label: 'Behavioural', hint: 'Past situations, STAR answers' },
  { value: 'technical', label: 'Technical', hint: 'Skills and problem solving' },
  { value: 'mixed', label: 'Mixed', hint: 'A bit of everything' },
  { value: 'case', label: 'Case', hint: 'Work through a client scenario' },
  { value: 'roleplay', label: 'Role-play', hint: 'Act out a client conversation' },
]
const STAGE_OPTIONS: DropdownOption<Opts['stage']>[] = [
  { value: 'screen', label: 'Screening call', hint: 'Short, recruiter-style' },
  { value: 'full', label: 'Full interview', hint: 'The standard round' },
  { value: 'final', label: 'Final round', hint: 'Deeper, more senior' },
]
const LENGTH_OPTIONS: DropdownOption<'questions' | 'minutes'>[] = [
  { value: 'questions', label: 'Questions' },
  { value: 'minutes', label: 'Minutes' },
]
const DIFFICULTY_OPTIONS: DropdownOption<Opts['difficulty']>[] = [
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
]
const STYLE_OPTIONS: DropdownOption<Opts['style']>[] = [
  { value: 'friendly', label: 'Friendly', hint: 'Warm, encouraging' },
  { value: 'neutral', label: 'Neutral', hint: 'Professional, even' },
  { value: 'tough', label: 'Tough', hint: 'Probing follow-ups' },
]
const RECORD_OPTIONS: DropdownOption<RecordMode>[] = [
  { value: 'webcam', label: 'Webcam + audio' },
  { value: 'avatar', label: 'Avatar + audio' },
  { value: 'both', label: 'Avatar and webcam side by side' },
  { value: 'audio', label: 'Audio only' },
  { value: 'off', label: "Don't record" },
]

type Form = Omit<PackInput, 'materials'>
const EMPTY: Form = {
  title: '',
  role: '',
  company: '',
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

const toRows = (ms: Material[]): MaterialRow[] =>
  ms.map((m) => ({ key: newKey(), name: m.name, kind: m.kind, source: m.source, text: m.text, synthetic: m.synthetic }))
const candidateCopies = (ms: Material[] | undefined) => toRows((ms ?? []).filter((m) => m.kind === 'candidate')).map((r) => ({ ...r, synthetic: false }))

export function packSummary(p: Pack) {
  const o = p.options
  const m = p.brief_meta
  if (m?.exists && m.kind === 'stations') {
    const mins = [...new Set(m.stations.map((s) => s.minutes))]
    const each = mins.length === 1 ? `${m.stations.length} × ${mins[0]} min` : `${m.stations.length} stations, ${m.total_minutes} min`
    return `stations · ${each} · ${o.difficulty} · ${o.style}`
  }
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
  const [form, setForm] = useState<Form>(EMPTY)
  const [rows, setRows] = useState<MaterialRow[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [meta, setMeta] = useState<BriefMeta | null>(null) // the edited pack's brief, if any
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [voices, setVoices] = useState<string[]>(['af_heart'])
  const [recordMode, setMode] = useState<RecordMode>(getRecordMode)
  const [faceOn, setFaceOn] = useState(getFaceTracking)
  const [faceModel, setFaceModel] = useState<boolean | null>(null) // null: still checking
  const [sessions, setSessions] = useState<SessionListItem[]>([])
  const [saved, setSaved] = useState<Pack | null>(null) // a new pack: offer to write its brief before starting

  useEffect(() => {
    void faceModelAvailable().then(setFaceModel)
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
        // The CV is saved once and reused: a new pack starts with the latest pack's candidate materials.
        if (list.length > 0 && !editPackId)
          api.getPack(list[0].id).then((p) => setRows((r) => (r.length ? r : candidateCopies(p.materials))), () => {})
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (editPackId) api.getPack(editPackId).then(editPack, (e: Error) => setError(e.message))
  }, [editPackId])

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))
  const setOpt = <K extends keyof PackInput['options']>(key: K, value: PackInput['options'][K]) =>
    setForm((f) => ({ ...f, options: { ...f.options, [key]: value } }))

  const editPack = (p: Pack) => {
    setEditingId(p.id)
    setMeta(p.brief_meta ?? null)
    setForm({ title: p.title, role: p.role, company: p.company, options: { ...EMPTY.options, ...p.options } })
    setRows(toRows(p.materials ?? []))
    window.scrollTo({ top: 0 })
  }
  const openPack = (p: Pack) => api.getPack(p.id).then(editPack, (e: Error) => setError(e.message))

  const stopEditing = () => {
    setEditingId(null)
    setMeta(null)
    setForm(EMPTY)
    setRows((r) => r.filter((m) => m.kind === 'candidate').map((m) => ({ ...m, key: newKey(), synthetic: false })))
    if (window.location.hash.startsWith('#/edit/')) window.history.replaceState(null, '', '#/')
  }

  const save = async (asNew: boolean) => {
    setError(null)
    setSaving(true)
    try {
      const title = form.title.trim() || [form.role, form.company].filter(Boolean).join(' @ ') || 'Untitled'
      const materials = toSave(rows)
      if (!materials.length) throw new Error('Add at least one material with text: the job advert, your CV, notes…')
      const data: PackInput = { ...form, title, materials }
      const pack = editingId && !asNew ? await api.updatePack(editingId, data) : await api.createPack(data)
      if (!editingId || asNew) {
        setSaved(pack)
        setSaving(false)
        return
      }
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

  const o = form.options
  // A stations brief fixes the format: type, stage and length come from it.
  const stations = meta?.exists && meta.kind === 'stations' ? meta : null
  const briefLength = stations ? `${stations.stations.length} stations, ${stations.total_minutes} min (from the brief)` : ''
  const settingsSummary = (
    stations
      ? [briefLength, o.difficulty, o.style]
      : [
          STAGE_OPTIONS.find((s) => s.value === o.stage)?.label,
          TYPE_OPTIONS.find((t) => t.value === o.interview_type)?.label,
          o.minutes ? `${o.minutes} min` : `${o.num_questions} questions`,
          o.difficulty,
          o.style,
        ]
  ).join(' · ')

  return (
    <div className="setup">
      <div className="page-head">
        <div>
          <p className="eyebrow">{editingId ? 'Editing pack' : 'Mock interview'}</p>
          <h1 className="page-title">{editingId ? form.title || 'Edit pack' : 'Prepare a new interview'}</h1>
          <p className="muted lede">
            Add the job advert, your CV and anything else you have. {o.interviewer_name || 'The interviewer'} will run a
            realistic interview from them, and you get a scored report afterwards.
          </p>
        </div>
        {editingId && (
          <button type="button" className="ghost" onClick={stopEditing}>
            Cancel editing
          </button>
        )}
      </div>

      <form className="setup-form" onSubmit={submit}>
        <section className="card section">
          <h2 className="section-title">
            <span className="step">1</span> The role
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
              <input value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="Role @ Company" />
            </label>
          </div>
        </section>

        <section className="card section">
          <h2 className="section-title">
            <span className="step">2</span> Materials
          </h2>
          <Materials rows={rows} onChange={setRows} company={form.company} role={form.role} onError={setError} />
        </section>

        <details className="card section disclosure" open>
          <summary>
            <span className="section-title">
              <span className="step">3</span> Interview settings
            </span>
            <span className="summary-meta muted small">{settingsSummary}</span>
            <Chevron />
          </summary>
          <div className="settings-grid">
            {stations ? (
              <div className="field wide">
                <span className="field-label">Format</span>
                <span>
                  {briefLength}. <a href={`#/brief/${editingId}`}>Change it in the interview brief</a>
                </span>
              </div>
            ) : (
              <>
                <div className="field">
                  <span className="field-label">Type</span>
                  <Dropdown ariaLabel="Interview type" value={o.interview_type} options={TYPE_OPTIONS} onChange={(v) => setOpt('interview_type', v)} />
                </div>
                <div className="field">
                  <span className="field-label">Stage</span>
                  <Dropdown ariaLabel="Interview stage" value={o.stage} options={STAGE_OPTIONS} onChange={(v) => setOpt('stage', v)} />
                </div>
                <div className="field">
                  <span className="field-label">Length</span>
                  <span className="length">
                    <Dropdown
                      ariaLabel="Length in"
                      value={o.minutes ? 'minutes' : 'questions'}
                      options={LENGTH_OPTIONS}
                      onChange={(v) => setOpt('minutes', v === 'minutes' ? 20 : null)}
                    />
                    {o.minutes ? (
                      <input aria-label="Minutes" type="number" min={5} max={120} step={5} value={o.minutes} onChange={(e) => setOpt('minutes', Number(e.target.value))} />
                    ) : (
                      <input aria-label="Questions" type="number" min={1} max={20} value={o.num_questions} onChange={(e) => setOpt('num_questions', Number(e.target.value))} />
                    )}
                  </span>
                </div>
              </>
            )}
            <div className="field">
              <span className="field-label">Difficulty</span>
              <Dropdown ariaLabel="Difficulty" value={o.difficulty} options={DIFFICULTY_OPTIONS} onChange={(v) => setOpt('difficulty', v)} />
            </div>
            <div className="field">
              <span className="field-label">Style</span>
              <Dropdown ariaLabel="Interviewer style" value={o.style} options={STYLE_OPTIONS} onChange={(v) => setOpt('style', v)} />
            </div>
            <label>
              Interviewer
              <input value={o.interviewer_name} onChange={(e) => setOpt('interviewer_name', e.target.value)} />
            </label>
            <div className="field">
              <span className="field-label">Voice</span>
              <Dropdown
                ariaLabel="Voice"
                value={o.voice}
                options={voices.map((v) => ({ value: v, label: voiceLabel(v) }))}
                onChange={(v) => setOpt('voice', v)}
              />
            </div>
            <div className="field wide">
              <span className="field-label">Recording</span>
              <Dropdown
                ariaLabel="Record the session"
                value={recordMode}
                options={RECORD_OPTIONS}
                onChange={(m) => {
                  setMode(m)
                  setRecordMode(m)
                }}
              />
            </div>
            <div className="field wide">
              <label className="inline">
                <input
                  type="checkbox"
                  checked={faceOn && faceModel === true}
                  disabled={faceModel !== true}
                  onChange={(e) => {
                    setFaceOn(e.target.checked)
                    setFaceTracking(e.target.checked)
                  }}
                />
                Track eye contact and expression (stays on this computer)
              </label>
              <span className="hint">
                {faceModel === false
                  ? 'Face model not installed: run scripts/fetch_face_model.sh once (see the README). Everything else works without it.'
                  : 'Needs the webcam in the recording ("Webcam + audio" or "Avatar and webcam side by side"). Only numbers are kept, never video frames.'}
              </span>
            </div>
          </div>
        </details>

        {error && <div className="banner error">{error}</div>}
        {saved && (
          <div className="banner confirm brief-offer">
            <span>
              <strong>Pack saved.</strong> An interview brief fits the interview to your materials: the format (a conversation, timed
              stations or a panel), the criteria (your mark scheme, if you added one) and what they will probe.
            </span>
            <a className="button-link primary" href={`#/brief/${saved.id}?generate=1`}>
              Write the interview brief (1 Claude request)
            </a>
            <button type="button" onClick={() => onStart(saved)}>
              Skip: use the standard interview
            </button>
          </div>
        )}
        <div className="form-actions">
          <button type="submit" className="primary large" disabled={saving || !!saved || totalChars(rows) > MAX_PACK_CHARS}>
            {saving ? 'Saving…' : editingId ? 'Save changes & start' : 'Save pack'}
            {!saving && <span aria-hidden> →</span>}
          </button>
          {editingId && (
            <button type="button" disabled={saving} onClick={() => void save(true)}>
              Save as a new pack
            </button>
          )}
        </div>
      </form>

      <aside className="sidebar">
        <section className="card">
          <h2 className="side-title">
            Saved packs <span className="count">{packs.length}</span>
          </h2>
          {packs.length === 0 && <p className="muted small empty">Packs you save appear here so you can rerun them.</p>}
          <div className="pack-list">
            {packs.map((p) => (
              <div key={p.id} className={`pack ${editingId === p.id ? 'current' : ''}`}>
                <div className="pack-info">
                  <strong>{p.title}</strong>
                  <div className="muted small">{packSummary(p)}</div>
                  {p.brief_meta?.exists && (p.brief_meta.to_confirm > 0 || p.brief_meta.stale) && (
                    <div className="small">
                      <a className="subtle-link" href={`#/brief/${p.id}`}>
                        {[
                          p.brief_meta.to_confirm > 0 && `${p.brief_meta.to_confirm} assumption${p.brief_meta.to_confirm === 1 ? '' : 's'} to confirm`,
                          p.brief_meta.stale && 'brief out of date',
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </a>
                    </div>
                  )}
                </div>
                <div className="pack-actions">
                  <a className="button-link small" href={`#/brief/${p.id}`}>
                    Interview brief
                  </a>
                  <a className="button-link small" href={`#/prep/${p.id}`}>
                    Prep
                  </a>
                  <a className="button-link small" href={`#/drill/${p.id}`}>
                    Drill
                  </a>
                  <button type="button" className="small ghost" onClick={() => void openPack(p)}>
                    Edit
                  </button>
                  <button type="button" className="primary small" onClick={() => onStart(p)}>
                    Start
                  </button>
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
                  <span className="score-chip">
                    {s.overall_score != null ? s.overall_score.toFixed(1) : s.report_status === 'pending' ? '…' : '–'}
                  </span>
                </a>
              ))}
            </div>
          </section>
        )}
      </aside>
    </div>
  )
}
