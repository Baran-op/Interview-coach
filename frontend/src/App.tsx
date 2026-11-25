import { useEffect, useState } from 'react'
import { api, type Pack } from './api'
import Setup from './pages/Setup'
import Interview from './pages/Interview'
import Review from './pages/Review'
import History from './pages/History'
import Drill from './pages/Drill'
import Prep from './pages/Prep'
import Brief from './pages/Brief'

type Screen =
  | { name: 'setup'; editPackId?: string }
  | { name: 'interview'; pack: Pack }
  | { name: 'review'; sessionId: string; tab: 'feedback' | 'voice'; q: number | null }
  | { name: 'history' }
  | { name: 'drill'; packId: string; q: string | null; from: string | null }
  | { name: 'prep'; packId: string }
  | { name: 'brief'; packId: string; generate: boolean }

// Tiny hash router: #/ (setup), #/edit/<pack id>, #/interview, #/review/<session id>, #/history, #/drill/<pack id>?q=<question>[&from=<session>~<turn>~<section>], #/review/<session id>[?tab=voice&q=<answer index>],
// #/prep/<pack id>, #/brief/<pack id>[?generate=1].
function fromHash(current: Screen): Screen {
  const hash = window.location.hash
  const review = hash.match(/^#\/review\/([\w-]+)(?:\?(.*))?/)
  if (review) {
    const qs = new URLSearchParams(review[2] ?? '')
    const q = qs.get('q')
    return { name: 'review', sessionId: review[1], tab: qs.get('tab') === 'voice' ? 'voice' : 'feedback', q: q != null && /^\d+$/.test(q) ? Number(q) : null }
  }
  const drill = hash.match(/^#\/drill\/([\w-]+)(?:\?(.*))?/)
  if (drill) {
    const qs = new URLSearchParams(drill[2] ?? '')
    return { name: 'drill', packId: drill[1], q: qs.get('q'), from: qs.get('from') }
  }
  const prep = hash.match(/^#\/prep\/([\w-]+)/)
  if (prep) return { name: 'prep', packId: prep[1] }
  const brief = hash.match(/^#\/brief\/([\w-]+)(?:\?(.*))?/)
  if (brief) return { name: 'brief', packId: brief[1], generate: new URLSearchParams(brief[2] ?? '').get('generate') === '1' }
  const edit = hash.match(/^#\/edit\/([\w-]+)/)
  if (edit) return { name: 'setup', editPackId: edit[1] }
  if (hash.startsWith('#/history')) return { name: 'history' }
  if (hash.startsWith('#/interview') && current.name === 'interview') return current
  return { name: 'setup' }
}

export default function App() {
  const [screen, setScreen] = useState<Screen>(() => fromHash({ name: 'setup' }))
  const [healthProblems, setHealthProblems] = useState<string[]>([])

  useEffect(() => {
    api
      .health()
      .then((h) => setHealthProblems(h.problems))
      .catch((e: Error) => setHealthProblems([e.message]))
  }, [])

  useEffect(() => {
    const onHash = () => setScreen((s) => fromHash(s))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (s: Screen, hash: string) => {
    setScreen(s)
    if (window.location.hash !== hash) window.history.pushState(null, '', hash)
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden>
            <svg width="14" height="14" viewBox="0 0 16 16">
              <path d="M3 3.5h10a1.5 1.5 0 0 1 1.5 1.5v5A1.5 1.5 0 0 1 13 11.5H8l-3.2 2.4a.5.5 0 0 1-.8-.4v-2H3A1.5 1.5 0 0 1 1.5 10V5A1.5 1.5 0 0 1 3 3.5Z" fill="currentColor" />
            </svg>
          </span>
          <span className="brand-name">Interview Coach</span>
        </a>
        {screen.name === 'interview' && <span className="topbar-context">{screen.pack.title}</span>}
        {screen.name !== 'interview' && (
          <nav className="nav">
            <a href="#/" className={screen.name === 'setup' ? 'active' : ''}>
              New interview
            </a>
            <a href="#/history" className={screen.name === 'history' ? 'active' : ''}>
              History
            </a>
          </nav>
        )}
      </header>
      {healthProblems.length > 0 && (
        <div className="banner error">
          {healthProblems.map((p) => (
            <div key={p}>{p}</div>
          ))}
        </div>
      )}
      <main>
        {screen.name === 'setup' && (
          <Setup
            key={screen.editPackId ?? 'new'}
            editPackId={screen.editPackId}
            onStart={(pack) => go({ name: 'interview', pack }, '#/interview')}
          />
        )}
        {screen.name === 'history' && <History onStart={(pack) => go({ name: 'interview', pack }, '#/interview')} />}
        {screen.name === 'drill' && <Drill key={screen.packId} packId={screen.packId} initialQuestion={screen.q} from={screen.from} />}
        {screen.name === 'prep' && <Prep key={screen.packId} packId={screen.packId} />}
        {screen.name === 'brief' && <Brief
            key={screen.packId}
            packId={screen.packId}
            generate={screen.generate}
            onStart={(pack) => go({ name: 'interview', pack }, '#/interview')}
          />}
        {screen.name === 'interview' && (
          <Interview
            pack={screen.pack}
            onExit={() => go({ name: 'setup' }, '#/')}
            onReview={(sessionId) => go({ name: 'review', sessionId, tab: 'feedback', q: null }, `#/review/${sessionId}`)}
          />
        )}
        {screen.name === 'review' && (
          <Review
            key={screen.sessionId}
            sessionId={screen.sessionId}
            tab={screen.tab}
            q={screen.q}
            onStart={(pack) => go({ name: 'interview', pack }, '#/interview')}
          />
        )}
      </main>
    </div>
  )
}
