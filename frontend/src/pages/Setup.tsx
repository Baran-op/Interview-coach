import { useEffect, useState, type FormEvent } from 'react'
import { api, MAX_PACK_CHARS, type BriefMeta, type Material, type Pack, type PackInput } from '../api'
import { getRecordMode, setRecordMode, type RecordMode } from '../audio/recorder'
import { faceModelAvailable, getFaceTracking, setFaceTracking } from '../face/FaceTracker'

import Dropdown, { Chevron, type DropdownOption } from '../components/Dropdown'
import Materials, { newKey, toSave, totalChars, type MaterialRow } from '../components/Materials'
import PackHeader from '../components/PackHeader'

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
/** What a save would send, to tell whether the form has unsaved edits. */
const snapshot = (form: Form, rows: MaterialRow[]) => JSON.stringify({ form, materials: toSave(rows) })
const label = <T extends string>(options: DropdownOption<T>[], v: T) => options.find((o) => o.value === v)?.label ?? v

interface Props {
  onStart: (pack: Pack) => void
  /** Open this pack for editing (#/edit/<id>): the pack's Materials tab. Without it, a new pack (#/new). */
  editPackId?: string
}

export default function Setup({ onStart, editPackId }: Props) {
  const [form, setForm] = useState<Form>(EMPTY)
  const [rows, setRows] = useState<MaterialRow[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<string | null>(null) // snapshot of the pack as loaded, for "unsaved edits"
  const [meta, setMeta] = useState<BriefMeta | null>(null) // the edited pack's brief, if any
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [voices, setVoices] = useState<string[]>(['af_heart'])
  const [recordMode, setMode] = useState<RecordMode>(getRecordMode)
  const [faceOn, setFaceOn] = useState(getFaceTracking)
  const [faceModel, setFaceModel] = useState<boolean | null>(null) // null: still checking
  const [saved, setSaved] = useState<Pack | null>(null) // a new pack: offer to write its brief before starting

  useEffect(() => {
    void faceModelAvailable().then(setFaceModel)
    api
      .voices()
      .then((v) => setVoices(v.voices))
      .catch(() => {})
    // The CV is saved once and reused: a new pack starts with the latest pack's candidate materials.
    if (!editPackId)
      api
        .listPacks()
        .then((list) => {
          if (list.length > 0) api.getPack(list[0].id).then((p) => setRows((r) => (r.length ? r : candidateCopies(p.materials))), () => {})
        })
        .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (editPackId) api.getPack(editPackId).then(editPack, (e: Error) => setError(e.message))
  }, [editPackId])

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))
  const setOpt = <K extends keyof PackInput['options']>(key: K, value: PackInput['options'][K]) =>
    setForm((f) => ({ ...f, options: { ...f.options, [key]: value } }))
  // Browsers don't enforce min/max on typed numbers and the backend rejects out-of-range ones:
  // cap the top while typing, raise the bottom on blur (so "120" can be typed via "1").
  const capped = (v: string, max: number) => Math.min(max, Math.floor(Number(v)) || 0)
  const floored = (v: number, min: number) => Math.max(min, v || 0)

  const editPack = (p: Pack) => {
    const f: Form = { title: p.title, role: p.role, company: p.company, options: { ...EMPTY.options, ...p.options } }
    const r = toRows(p.materials ?? [])
    setEditingId(p.id)
    setMeta(p.brief_meta ?? null)
    setForm(f)
    setRows(r)
    setLoaded(snapshot(f, r))
    window.scrollTo({ top: 0 })
  }

  const dirty = !!editingId && loaded != null && snapshot(form, rows) !== loaded

  // Discards the edits, as before; Home is where the saved packs are now.
  const stopEditing = () => {
    window.location.hash = '#/'
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
      ? [briefLength, `${label(DIFFICULTY_OPTIONS, o.difficulty)} difficulty`, `${label(STYLE_OPTIONS, o.style)} interviewer`]
      : [
          label(STAGE_OPTIONS, o.stage),
          label(TYPE_OPTIONS, o.interview_type),
          o.minutes ? `${o.minutes} min` : `${o.num_questions} questions`,
          `${label(DIFFICULTY_OPTIONS, o.difficulty)} difficulty`,
          `${label(STYLE_OPTIONS, o.style)} interviewer`,
        ]
  ).join(' · ')

  return (
    <div className="setup">
      {editPackId ? (
        <PackHeader
          packId={editPackId}
          tab="materials"
          primary={false}
          disabled={saving}
          onStart={onStart}
          confirmStart={() => !dirty || window.confirm('Start without saving your changes to this pack?')}
        />
      ) : (
        <div className="page-head">
          <div>
            <p className="eyebrow">New pack</p>
            <h1 className="page-title">Prepare a new interview</h1>
            <p className="muted lede">
              Add the job advert, your CV and anything else you have. {o.interviewer_name || 'The interviewer'} will run a
              realistic interview from them, and you get a scored report afterwards.
            </p>
          </div>
        </div>
      )}

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
          <div className="settings-groups">
            <fieldset className="settings-group">
              <legend>Interview</legend>
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
                          value={o.minutes != null ? 'minutes' : 'questions'}
                          options={LENGTH_OPTIONS}
                          onChange={(v) => setOpt('minutes', v === 'minutes' ? 20 : null)}
                        />
                        {o.minutes != null ? (
                          <input aria-label="Minutes" type="number" min={5} max={120} step={5} value={o.minutes} onChange={(e) => setOpt('minutes', capped(e.target.value, 120))} onBlur={() => setOpt('minutes', floored(o.minutes ?? 0, 5))} />
                        ) : (
                          <input aria-label="Questions" type="number" min={1} max={20} value={o.num_questions} onChange={(e) => setOpt('num_questions', capped(e.target.value, 20))} onBlur={() => setOpt('num_questions', floored(o.num_questions, 1))} />
                        )}
                      </span>
                    </div>
                  </>
                )}
                <div className="field">
                  <span className="field-label">Difficulty</span>
                  <Dropdown ariaLabel="Difficulty" value={o.difficulty} options={DIFFICULTY_OPTIONS} onChange={(v) => setOpt('difficulty', v)} />
                </div>
              </div>
            </fieldset>

            <fieldset className="settings-group">
              <legend>Interviewer</legend>
              <div className="settings-grid">
                <label>
                  Name
                  <input value={o.interviewer_name} onChange={(e) => setOpt('interviewer_name', e.target.value)} />
                </label>
                <div className="field">
                  <span className="field-label">Style</span>
                  <Dropdown ariaLabel="Interviewer style" value={o.style} options={STYLE_OPTIONS} onChange={(v) => setOpt('style', v)} />
                </div>
                <div className="field">
                  <span className="field-label">Voice</span>
                  <Dropdown
                    ariaLabel="Voice"
                    value={o.voice}
                    options={voices.map((v) => ({ value: v, label: voiceLabel(v) }))}
                    onChange={(v) => setOpt('voice', v)}
                  />
                </div>
              </div>
            </fieldset>

            <fieldset className="settings-group">
              <legend>Recording</legend>
              <div className="settings-grid">
                <div className="field wide">
                  <span className="field-label">Record the session</span>
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
            </fieldset>
          </div>
        </details>

        {error && <div className="banner error">{error}</div>}
        {saved ? (
          // The brief prompt takes the Save button's place once the pack is saved.
          <div className="card brief-offer" role="status">
            <p>
              <strong>Pack saved.</strong> An interview brief fits the interview to your materials: the format (a conversation, timed
              stations or a panel), the criteria (your mark scheme, if you added one) and what they will probe.
            </p>
            <div className="brief-offer-actions">
              <a className="button-link primary" href={`#/brief/${saved.id}?generate=1`}>
                Write the interview brief (1 Claude request)
              </a>
              <button type="button" onClick={() => onStart(saved)}>
                Skip: use the standard interview
              </button>
            </div>
          </div>
        ) : (
          <div className="form-actions">
            <button type="submit" className="primary large" disabled={saving || totalChars(rows) > MAX_PACK_CHARS}>
              {saving ? 'Saving…' : editingId ? 'Save changes & start' : 'Save pack'}
              {!saving && <span aria-hidden> →</span>}
            </button>
            {editingId && (
              <button type="button" disabled={saving} onClick={() => void save(true)}>
                Save as a new pack
              </button>
            )}
            {editingId && (
              <button type="button" className="ghost" onClick={stopEditing}>
                Cancel editing
              </button>
            )}
            {dirty && <span className="small unsaved">Unsaved changes</span>}
          </div>
        )}
      </form>
    </div>
  )
}
