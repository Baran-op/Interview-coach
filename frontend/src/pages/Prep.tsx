import { useEffect, useState } from 'react'
import { api, CATEGORY_LABEL, type Pack, type PrepResponse, type PrepSheet } from '../api'
import PackHeader from '../components/PackHeader'

const label = (key: string, labels?: Record<string, string>) => labels?.[key] ?? CATEGORY_LABEL[key] ?? key

/** The sheet as Markdown, for download. */
export function prepMarkdown(pack: Pack, sheet: PrepSheet, labels?: Record<string, string>): string {
  const out: string[] = [`# Prep sheet: ${pack.title}`, '']
  out.push('## Likely questions', '')
  sheet.likely_questions.forEach((q, i) => {
    out.push(`${i + 1}. **${q.question}** (${label(q.category, labels)})`)
    if (q.why) out.push(`   - Tests: ${q.why}`)
  })
  out.push('', '## CV against the job', '')
  for (const g of sheet.gaps) {
    out.push(`- **${g.requirement}**: ${g.cv_evidence ? `evidence: ${g.cv_evidence}` : 'MISSING from the CV'}`)
    if (g.how_to_address) out.push(`  - How to address: ${g.how_to_address}`)
  }
  if (sheet.stories.length) out.push('', '## STAR stories', '')
  for (const s of sheet.stories) {
    out.push(`### ${s.title}`, '')
    if (s.competencies.length) out.push(`Shows: ${s.competencies.join(', ')}`, '')
    out.push(`- **Situation:** ${s.situation}`, `- **Task:** ${s.task}`, `- **Action:** ${s.action}`, `- **Result:** ${s.result}`)
    if (s.numbers.length) out.push(`- **Numbers:** ${s.numbers.join('; ')}`)
    out.push('')
  }
  if (sheet.questions_to_ask.length) out.push('## Questions to ask', '')
  sheet.questions_to_ask.forEach((q) => out.push(`- ${q}`))
  return out.join('\n') + '\n'
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default function Prep({ packId, onStart }: { packId: string; onStart: (pack: Pack) => void }) {
  const [pack, setPack] = useState<Pack | null>(null)
  const [data, setData] = useState<PrepResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getPack(packId).then(setPack).catch((e) => setError(String(e.message ?? e)))
    api.getPrep(packId).then(setData).catch((e) => setError(String(e.message ?? e)))
  }, [packId])

  async function write() {
    const rewrite = !!data?.prep
    if (rewrite && !window.confirm('Rewrite the prep sheet? This costs one Claude request and replaces the current sheet.')) return
    setBusy(true)
    setError(null)
    try {
      setData(await api.writePrep(packId))
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const sheet = data?.prep ?? null
  return (
    <div className="pack-page">
    <PackHeader packId={packId} tab="prep" onStart={onStart} />
    <div className="card prep">
      <div className="prep-toolbar">
        <div>
          <h2>Prep sheet</h2>
          {data?.created_at && <div className="muted small">Written {new Date(data.created_at).toLocaleString()}</div>}
        </div>
        <div className="actions">
          {pack && sheet && (
            <button type="button" onClick={() => download(`prep-${pack.title.replace(/\W+/g, '-')}.md`, prepMarkdown(pack, sheet, data?.labels))}>
              Download Markdown
            </button>
          )}
          <button type="button" disabled={busy || !data} onClick={() => void write()}>
            {busy ? 'Writing…' : sheet ? 'Rewrite (costs 1 request)' : 'Write prep sheet (costs 1 request)'}
          </button>
        </div>
      </div>

      {error && <div className="banner error">{error}</div>}
      {data?.stale && (
        <div className="banner">Your materials or interview brief have changed since this sheet was written. Rewrite it to bring it up to date.</div>
      )}
      {!sheet && data && !busy && <p className="muted">No prep sheet yet. It takes one Claude request and a minute or so.</p>}

      {sheet && (
        <>
          <h3>Likely questions</h3>
          <ol>
            {sheet.likely_questions.map((q) => (
              <li key={q.question}>
                <strong>{q.question}</strong> <span className="muted small">{label(q.category, data?.labels)}</span>{' '}
                <a className="button-link" href={`#/drill/${packId}?q=${encodeURIComponent(q.question)}`}>Practise</a>
                {q.why && <div className="muted small">{q.why}</div>}
              </li>
            ))}
          </ol>

          <h3>CV against the job</h3>
          <div className="table-wrap">
            <table className="sessions">
              <thead>
                <tr><th scope="col">Requirement</th><th scope="col">CV evidence</th><th scope="col">How to address it</th></tr>
              </thead>
              <tbody>
                {sheet.gaps.map((g) => (
                  <tr key={g.requirement}>
                    <td>{g.requirement}</td>
                    <td>{g.cv_evidence ?? <strong>Missing</strong>}</td>
                    <td>{g.how_to_address}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sheet.stories.length > 0 && <h3>STAR stories</h3>}
          {sheet.stories.map((s) => (
            <details key={s.title} className="story">
              <summary>
                <strong>{s.title}</strong> <span className="muted small">{s.competencies.join(', ')}</span>
              </summary>
              <p><strong>Situation.</strong> {s.situation}</p>
              <p><strong>Task.</strong> {s.task}</p>
              <p><strong>Action.</strong> {s.action}</p>
              <p><strong>Result.</strong> {s.result}</p>
              {s.numbers.length > 0 && <p className="muted small">Numbers: {s.numbers.join('; ')}</p>}
            </details>
          ))}

          {sheet.questions_to_ask.length > 0 && <h3>Questions to ask</h3>}
          <ul>
            {sheet.questions_to_ask.map((q) => <li key={q}>{q}</li>)}
          </ul>
        </>
      )}
    </div>
    </div>
  )
}
