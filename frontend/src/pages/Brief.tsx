import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Assumption, type Brief as BriefT, type BriefCategory, type BriefState, type CriterionDef, type FormatKind, type Pack } from '../api'
import Dropdown, { Chevron, type DropdownOption } from '../components/Dropdown'

const KIND_OPTIONS: DropdownOption<FormatKind>[] = [
  { value: 'conversation', label: 'Conversation', hint: 'One interviewer, question by question' },
  { value: 'stations', label: 'Stations', hint: 'Timed scenarios, one after another' },
  { value: 'panel', label: 'Panel', hint: 'Several interviewers, one voice' },
]
const ORIGIN_LABEL: Record<BriefState['origin'], string> = { generated: 'Generated', edited: 'Edited', standard: 'Standard interview' }
const SOURCE_LABEL: Record<CriterionDef['source'], string> = {
  provided: 'from your mark scheme',
  inferred: 'written by Claude',
  default: 'standard',
}
const REGENERATE_NOTE = '1 Claude request. Your unsaved edits are lost; your answers to the questions above are sent along.'

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** One item per line; empty lines are dropped by the server. */
function Lines({ label, value, onChange, rows = 4 }: { label: string; value: string[]; onChange: (v: string[]) => void; rows?: number }) {
  return (
    <label>
      {label}
      <textarea rows={rows} value={value.join('\n')} onChange={(e) => onChange(e.target.value.split('\n'))} />
      <span className="hint">One per line.</span>
    </label>
  )
}

function Section({ title, meta, children, open }: { title: string; meta?: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="card section disclosure" open={open || undefined}>
      <summary>
        <span className="section-title">{title}</span>
        {meta && <span className="summary-meta muted small">{meta}</span>}
        <Chevron />
      </summary>
      <div className="brief-body">{children}</div>
    </details>
  )
}

export default function Brief({ packId, generate }: { packId: string; generate?: boolean }) {
  const [pack, setPack] = useState<Pack | null>(null)
  const [state, setState] = useState<BriefState | null>(null)
  const [draft, setDraft] = useState<BriefT | null>(null)
  const [busy, setBusy] = useState<null | 'generating' | 'saving'>(null)
  const [error, setError] = useState<string | null>(null)
  const [replace, setReplace] = useState(false)
  const autoRan = useRef(false)
  const [rev, setRev] = useState(0) // remounts editors with local state when the draft is replaced

  const load = (s: BriefState) => {
    setState(s)
    setDraft(clone(s.brief))
    setRev((r) => r + 1)
  }

  useEffect(() => {
    api.getPack(packId).then(setPack, (e: Error) => setError(e.message))
    api.getBrief(packId).then(load, (e: Error) => setError(e.message))
  }, [packId])

  const run = async (what: 'generating' | 'saving', fn: () => Promise<BriefState>) => {
    setBusy(what)
    setError(null)
    try {
      load(await fn())
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(null)
    }
  }

  const generate_ = async (ask: boolean) => {
    if (!state || !draft) return
    if (ask && !window.confirm(state.is_default ? 'Write the interview brief from your materials? This spends 1 Claude request.' : REGENERATE_NOTE)) return
    // Your answers to the questions are part of the saved brief: save them first so they are sent along.
    if (!state.is_default && !same(draft.assumptions, state.brief.assumptions)) {
      const ok = await run('saving', () => api.saveBrief(packId, { ...state.brief, assumptions: draft.assumptions }))
      if (!ok) return
    }
    await run('generating', () => api.generateBrief(packId, replace))
    setReplace(false)
  }

  useEffect(() => {
    if (generate && state?.is_default && !autoRan.current) {
      autoRan.current = true
      window.history.replaceState(null, '', `#/brief/${packId}`)
      void generate_(false) // you already chose "Write the interview brief (1 Claude request)" in Setup
    }
  }, [generate, state]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Save `b`; true when saved. Reloads the draft from the server's cleaned copy. */
  const save = async (b: BriefT, opts: { acceptMaterials?: boolean } = {}): Promise<boolean> => {
    setBusy('saving')
    setError(null)
    try {
      load(await api.saveBrief(packId, b, opts))
      return true
    } catch (e) {
      const err = e as Error & { status?: number }
      if (err.status === 409 && state) {
        const n = state.scored_sessions
        const msg =
          `This pack has ${n} scored session${n === 1 ? '' : 's'}. Changing criteria or categories starts History comparisons fresh: ` +
          "earlier sessions stay as they were, but trends and 'since last time' only compare sessions scored the same way."
        if (window.confirm(msg)) {
          try {
            load(await api.saveBrief(packId, b, { ...opts, freshStart: true }))
            return true
          } catch (e2) {
            setError((e2 as Error).message)
          }
        }
      } else setError(err.message)
      return false
    } finally {
      setBusy(null)
    }
  }

  const reset = () => {
    if (!window.confirm('Go back to the standard interview? This brief is deleted (your materials stay). Free.')) return
    void run('saving', () => api.resetBrief(packId))
  }

  if (!state || !draft) {
    return <div className="card">{error ? <div className="banner error">{error}</div> : <p className="muted">Loading…</p>}</div>
  }

  const ro = state.is_default
  const dirty = !same(draft, state.brief)
  const set = (patch: Partial<BriefT>) => setDraft({ ...draft, ...patch })
  const setFormat = (patch: Partial<BriefT['format']>) => set({ format: { ...draft.format, ...patch } })
  const setAt = <K extends 'criteria' | 'categories' | 'likely_questions'>(key: K, i: number, patch: Partial<BriefT[K][number]>) =>
    set({ [key]: draft[key].map((x, j) => (j === i ? { ...x, ...patch } : x)) } as Partial<BriefT>)
  const setStation = (i: number, patch: Partial<BriefT['format']['stations'][number]>) =>
    setFormat({ stations: draft.format.stations.map((s, j) => (j === i ? { ...s, ...patch } : s)) })
  const setPanel = (i: number, patch: Partial<BriefT['format']['panel'][number]>) =>
    setFormat({ panel: draft.format.panel.map((p, j) => (j === i ? { ...p, ...patch } : p)) })
  const setAssumption = (id: string, patch: Partial<Assumption>) =>
    set({ assumptions: draft.assumptions.map((a) => (a.id === id ? { ...a, ...patch } : a)) })
  const categoryOptions: DropdownOption<string>[] = draft.categories.filter((c) => c.key).map((c) => ({ value: c.key, label: c.label }))
  const f = draft.format
  const stationMinutes = f.stations.reduce((n, s) => n + (Number(s.minutes) || 0), 0)
  const open = draft.assumptions.filter((a) => !a.confirmed)

  const confirmOne = async (a: Assumption) => {
    const keep = draft
    const assumptions = draft.assumptions.map((x) => (x.id === a.id ? { ...x, confirmed: true } : x))
    // Only the assumptions are saved (so a confirm never trips the criteria freeze); other unsaved edits stay in the draft.
    if (await save({ ...state.brief, assumptions })) {
      setDraft({ ...keep, assumptions })
      setRev((r) => r + 1)
    }
  }

  return (
    <div className="brief">
      <div className="page-head">
        <div>
          <p className="eyebrow">Interview brief</p>
          <h1 className="page-title">{pack?.title ?? 'Interview brief'}</h1>
          <p className="muted small">
            {ORIGIN_LABEL[state.origin]}
            {state.updated_at ? ` · updated ${new Date(state.updated_at).toLocaleString()}` : ''}
            {draft.field ? ` · ${draft.field}` : ''}
          </p>
        </div>
        <div className="actions">
          <a className="button-link" href={`#/edit/${packId}`}>Materials</a>
          <a className="button-link" href={`#/prep/${packId}`}>Prep</a>
          <a className="button-link" href={`#/drill/${packId}`}>Drill</a>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}
      {busy === 'generating' && <div className="banner">Writing the brief from your materials (a minute or so)…</div>}

      {ro && (
        <div className="banner confirm brief-intro">
          <span>
            This pack uses the <strong>standard interview</strong>: a one-to-one job interview scored on relevance, structure,
            specificity and evidence, run from your materials as they are. Write a brief to fit the interview to them: any
            profession, timed stations or a panel, your own mark scheme.
          </span>
          <button type="button" className="primary" disabled={!!busy} onClick={() => void generate_(true)}>
            Write the interview brief (1 Claude request)
          </button>
        </div>
      )}

      {!ro && state.stale && (
        <div className="banner">
          <span>Your materials changed since this brief was written. Regenerate (1 Claude request) or keep it.</span>
          <button type="button" className="small" disabled={!!busy} onClick={() => void generate_(true)}>
            Regenerate
          </button>
          <button type="button" className="small ghost" disabled={!!busy} onClick={() => void save(state.brief, { acceptMaterials: true })}>
            Keep it
          </button>
        </div>
      )}

      {!ro && open.length > 0 && (
        <section className="card section to-confirm">
          <h2 className="section-title">
            To confirm <span className="count">{open.length}</span>
          </h2>
          <p className="muted small">
            Claude guessed these rather than reading them in your materials. Answer to correct a guess (your answers are sent along when you
            regenerate), or confirm it. You can start interviews without confirming.
          </p>
          <ul className="assumptions">
            {open.map((a) => (
              <li key={a.id}>
                <div>
                  <span className="chip">{a.section}</span> {a.text}
                </div>
                {a.question && <div className="muted small">{a.question}</div>}
                <div className="assumption-answer">
                  <input aria-label="Your answer" placeholder="Your answer (optional)" value={a.answer} onChange={(e) => setAssumption(a.id, { answer: e.target.value })} />
                  <button type="button" className="small" disabled={!!busy} onClick={() => void confirmOne(a)}>
                    Confirm
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <fieldset className="brief-sections" disabled={ro || !!busy}>
        <Section title="Format" meta={`${f.kind}${f.kind === 'stations' ? ` · ${f.stations.length} × stations, ${stationMinutes} min` : f.total_minutes ? ` · ${f.total_minutes} min` : ''}`} open={!ro}>
          <div className="row">
            <label>
              Field
              <input value={draft.field} maxLength={60} onChange={(e) => set({ field: e.target.value })} />
            </label>
            <label>
              Role
              <input value={draft.role} maxLength={80} onChange={(e) => set({ role: e.target.value })} />
            </label>
            <label>
              Organisation
              <input value={draft.organisation} maxLength={80} onChange={(e) => set({ organisation: e.target.value })} />
            </label>
            <label>
              Level
              <input value={draft.level} maxLength={60} onChange={(e) => set({ level: e.target.value })} />
            </label>
          </div>
          <div className="settings-grid">
            <div className="field">
              <span className="field-label">Kind</span>
              <Dropdown ariaLabel="Format kind" value={f.kind} options={KIND_OPTIONS} disabled={ro} onChange={(v) => setFormat({ kind: v })} />
            </div>
            <label>
              Minutes
              {f.kind === 'stations' ? (
                <input value={`${stationMinutes} (sum of the stations)`} disabled />
              ) : (
                <input
                  type="number"
                  min={5}
                  max={180}
                  value={f.total_minutes ?? ''}
                  placeholder="Not timed"
                  onChange={(e) => setFormat({ total_minutes: e.target.value ? Number(e.target.value) : null })}
                />
              )}
            </label>
            <label className="inline">
              <input type="checkbox" checked={f.opening} onChange={(e) => setFormat({ opening: e.target.checked })} />
              Opens with “tell me about yourself”
            </label>
            <label className="inline">
              <input type="checkbox" checked={f.candidate_questions} onChange={(e) => setFormat({ candidate_questions: e.target.checked })} />
              Ends with your questions for them
            </label>
          </div>
          <label>
            Summary
            <textarea rows={3} maxLength={400} value={f.summary} onChange={(e) => setFormat({ summary: e.target.value })} />
          </label>
          {f.kind === 'stations' && (
            <div className="brief-list">
              <h3>Stations</h3>
              {f.stations.map((s, i) => (
                <div key={i} className="brief-item">
                  <div className="row">
                    <label>
                      Name
                      <input value={s.name} onChange={(e) => setStation(i, { name: e.target.value })} />
                    </label>
                    <label className="narrow">
                      Minutes
                      <input type="number" min={1} max={60} value={s.minutes} onChange={(e) => setStation(i, { minutes: Number(e.target.value) })} />
                    </label>
                    <div className="field">
                      <span className="field-label">Category</span>
                      <Dropdown ariaLabel="Station category" value={s.category} options={categoryOptions} disabled={ro} onChange={(v) => setStation(i, { category: v })} />
                    </div>
                  </div>
                  <label>
                    What it tests and how it runs
                    <textarea rows={2} maxLength={600} value={s.brief} onChange={(e) => setStation(i, { brief: e.target.value })} />
                  </label>
                  <label>
                    Scenario read out to you (optional)
                    <textarea rows={3} maxLength={1500} value={s.scenario ?? ''} onChange={(e) => setStation(i, { scenario: e.target.value || null })} />
                  </label>
                  <button type="button" className="small ghost" onClick={() => setFormat({ stations: f.stations.filter((_, j) => j !== i) })}>
                    Remove station
                  </button>
                </div>
              ))}
              {f.stations.length < 8 && (
                <button
                  type="button"
                  className="small"
                  onClick={() => setFormat({ stations: [...f.stations, { key: '', name: `Station ${f.stations.length + 1}`, minutes: 10, category: 'other', brief: '', scenario: null }] })}
                >
                  Add station
                </button>
              )}
            </div>
          )}
          {f.kind === 'panel' && (
            <div className="brief-list">
              <h3>Panel (2 to 4; one voice plays them all)</h3>
              {f.panel.map((p, i) => (
                <div key={i} className="row brief-item">
                  <label>
                    Name
                    <input value={p.name} onChange={(e) => setPanel(i, { name: e.target.value })} />
                  </label>
                  <label>
                    Role
                    <input value={p.role} onChange={(e) => setPanel(i, { role: e.target.value })} />
                  </label>
                  <label>
                    Focus
                    <input value={p.focus} onChange={(e) => setPanel(i, { focus: e.target.value })} />
                  </label>
                  <button type="button" className="small ghost" onClick={() => setFormat({ panel: f.panel.filter((_, j) => j !== i) })}>
                    Remove
                  </button>
                </div>
              ))}
              {f.panel.length < 4 && (
                <button type="button" className="small" onClick={() => setFormat({ panel: [...f.panel, { name: '', role: '', focus: '' }] })}>
                  Add member
                </button>
              )}
            </div>
          )}
        </Section>

        <Section title="Criteria" meta={draft.criteria.map((c) => c.name).join(' · ')}>
          {draft.criteria.every((c) => c.source === 'default') && (
            <p className="muted small">No mark scheme was provided, so these are the app’s four standard criteria, word for word.</p>
          )}
          {draft.criteria.map((c, i) => (
            <div key={i} className="brief-item">
              <div className="row">
                <label>
                  Name <span className="chip">{SOURCE_LABEL[c.source]}</span>
                  <input value={c.name} maxLength={60} onChange={(e) => setAt('criteria', i, { name: e.target.value })} />
                </label>
              </div>
              <label>
                What it rewards
                <textarea rows={2} value={c.description} onChange={(e) => setAt('criteria', i, { description: e.target.value })} />
              </label>
              <div className="row anchors">
                {(['1', '3', '5'] as const).map((k) => (
                  <label key={k}>
                    {k} =
                    <textarea rows={2} value={c.anchors[k]} onChange={(e) => setAt('criteria', i, { anchors: { ...c.anchors, [k]: e.target.value } })} />
                  </label>
                ))}
              </div>
              {c.source === 'provided' && (
                <label>
                  How the scheme’s scale maps onto 1-5
                  <input value={c.scale_note} onChange={(e) => setAt('criteria', i, { scale_note: e.target.value })} />
                </label>
              )}
              {draft.criteria.length > 3 && (
                <button type="button" className="small ghost" onClick={() => set({ criteria: draft.criteria.filter((_, j) => j !== i) })}>
                  Remove criterion
                </button>
              )}
            </div>
          ))}
          {draft.criteria.length < 6 && (
            <button
              type="button"
              className="small"
              onClick={() => set({ criteria: [...draft.criteria, { key: '', name: '', description: '', anchors: { '1': '', '3': '', '5': '' }, source: 'inferred', scale_note: '' }] })}
            >
              Add criterion
            </button>
          )}
        </Section>

        <Section title="Categories" meta={draft.categories.map((c) => c.label).join(' · ')}>
          {draft.categories.map((c, i) => (
            <CategoryEditor
              key={`${rev}-${i}`}
              c={c}
              onChange={(patch) => setAt('categories', i, patch)}
              onRemove={c.key === 'other' ? undefined : () => set({ categories: draft.categories.filter((_, j) => j !== i) })}
            />
          ))}
          {draft.categories.length < 10 && (
            <button
              type="button"
              className="small"
              onClick={() => {
                const cats = [...draft.categories]
                cats.splice(Math.max(0, cats.length - 1), 0, { key: '', label: '', description: '', structure_hint: '', scoring_note: '', target_seconds: null })
                set({ categories: cats })
              }}
            >
              Add category
            </button>
          )}
        </Section>

        <Section title="What they'll probe" meta={`${draft.competencies.filter(Boolean).length} competencies · ${draft.likely_questions.length} questions`}>
          <Lines label="Competencies" value={draft.competencies} onChange={(v) => set({ competencies: v })} />
          <Lines label="Probes (gaps a sceptical interviewer would test)" value={draft.probes} onChange={(v) => set({ probes: v })} />
          <h3>Likely questions</h3>
          {draft.likely_questions.map((q, i) => (
            <div key={i} className="row brief-item">
              <label className="grow">
                Question
                <input value={q.question} onChange={(e) => setAt('likely_questions', i, { question: e.target.value })} />
              </label>
              <div className="field">
                <span className="field-label">Category</span>
                <Dropdown ariaLabel="Question category" value={q.category} options={categoryOptions} disabled={ro} onChange={(v) => setAt('likely_questions', i, { category: v })} />
              </div>
              <label className="grow">
                What it tests
                <input value={q.why} onChange={(e) => setAt('likely_questions', i, { why: e.target.value })} />
              </label>
              <button type="button" className="small ghost" onClick={() => set({ likely_questions: draft.likely_questions.filter((_, j) => j !== i) })}>
                Remove
              </button>
            </div>
          ))}
          {draft.likely_questions.length < 15 && (
            <button type="button" className="small" onClick={() => set({ likely_questions: [...draft.likely_questions, { question: '', category: 'other', why: '' }] })}>
              Add question
            </button>
          )}
        </Section>

        <Section title="Organisation facts" meta={`${draft.facts.filter(Boolean).length} facts`}>
          <Lines label="Facts (only from your materials)" value={draft.facts} onChange={(v) => set({ facts: v })} rows={6} />
        </Section>

        <Section title="About you" meta={draft.candidate_summary ? `${draft.candidate_facts.length.toLocaleString()} chars of facts` : 'From your materials'}>
          <label>
            Summary for the interviewer
            <textarea rows={5} maxLength={1200} value={draft.candidate_summary} onChange={(e) => set({ candidate_summary: e.target.value })} />
          </label>
          <label>
            Facts for scoring, prep and model answers (roles, projects, tools, numbers)
            <textarea rows={10} maxLength={4000} value={draft.candidate_facts} onChange={(e) => set({ candidate_facts: e.target.value })} />
          </label>
        </Section>
      </fieldset>

      {!ro && (
        <div className="form-actions brief-actions">
          <button type="button" className="primary" disabled={!dirty || !!busy} onClick={() => void save(draft)}>
            {busy === 'saving' ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
          </button>
          {dirty && (
            <button type="button" className="ghost" disabled={!!busy} onClick={() => load(state)}>
              Discard changes
            </button>
          )}
          <button type="button" disabled={!!busy} onClick={() => void generate_(true)}>
            {busy === 'generating' ? 'Writing…' : 'Regenerate (1 Claude request)'}
          </button>
          {state.frozen && (
            <label className="inline small">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              Also replace criteria and categories (History starts fresh)
            </label>
          )}
          <button type="button" className="ghost" disabled={!!busy} onClick={reset}>
            Use the standard interview
          </button>
        </div>
      )}
    </div>
  )
}

function CategoryEditor({ c, onChange, onRemove }: { c: BriefCategory; onChange: (p: Partial<BriefCategory>) => void; onRemove?: () => void }) {
  // Kept as text so a half-typed range survives; the brief only gets a range once both ends are set.
  const [lo, setLo] = useState(c.target_seconds ? String(c.target_seconds[0]) : '')
  const [hi, setHi] = useState(c.target_seconds ? String(c.target_seconds[1]) : '')
  const setTarget = (a: string, b: string) => {
    setLo(a)
    setHi(b)
    onChange({ target_seconds: Number(a) > 0 && Number(b) > 0 ? [Number(a), Number(b)] : null })
  }
  return (
    <div className="brief-item">
      <div className="row">
        <label>
          Label {c.key && <code className="muted small">{c.key}</code>}
          <input value={c.label} maxLength={40} onChange={(e) => onChange({ label: e.target.value })} />
        </label>
        <label className="grow">
          Description
          <input value={c.description} maxLength={120} onChange={(e) => onChange({ description: e.target.value })} />
        </label>
        <label className="narrow">
          Target from (s)
          <input type="number" min={10} value={lo} onChange={(e) => setTarget(e.target.value, hi)} />
        </label>
        <label className="narrow">
          to (s)
          <input type="number" min={10} value={hi} onChange={(e) => setTarget(lo, e.target.value)} />
        </label>
      </div>
      <label>
        Shape of a good answer
        <input value={c.structure_hint} maxLength={400} onChange={(e) => onChange({ structure_hint: e.target.value })} />
      </label>
      <label>
        Extra scoring rule (optional)
        <textarea rows={2} maxLength={700} value={c.scoring_note} onChange={(e) => onChange({ scoring_note: e.target.value })} />
      </label>
      {onRemove && (
        <button type="button" className="small ghost" onClick={onRemove}>
          Remove category
        </button>
      )}
    </div>
  )
}
