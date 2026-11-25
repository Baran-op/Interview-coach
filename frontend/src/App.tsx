import { useEffect, useState } from 'react'
import { api, type Pack } from './api'
import Setup from './pages/Setup'
import Interview from './pages/Interview'
import Review from './pages/Review'
import History from './pages/History'
import Drill from './pages/Drill'
import Prep from './pages/Prep'

type Screen =
  | { name: 'setup'; editPackId?: string }
  | { name: 'interview'; pack: Pack }
  | { name: 'review'; sessionId: string }
  | { name: 'history' }
  | { name: 'drill'; packId: string; q: string | null }
  | { name: 'prep'; packId: string }

// Tiny hash router: #/ (setup), #/edit/<pack id>, #/interview, #/review/<session id>, #/history, #/drill/<pack id>?q=<question>, #/prep/<pack id>.
function fromHash(current: Screen): Screen {
  const hash = window.location.hash
  const review = hash.match(/^#\/review\/([\w-]+)/)
  if (review) return { name: 'review', sessionId: review[1] }
  const drill = hash.match(/^#\/drill\/([\w-]+)(?:\?(.*))?/)
  if (drill) return { name: 'drill', packId: drill[1], q: new URLSearchParams(drill[2] ?? '').get('q') }
  const prep = hash.match(/^#\/prep\/([\w-]+)/)
  if (prep) return { name: 'prep', packId: prep[1] }
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
          Interview Coach
        </a>
        {screen.name === 'interview' && <span className="muted">{screen.pack.title}</span>}
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
        {screen.name === 'drill' && <Drill key={screen.packId} packId={screen.packId} initialQuestion={screen.q} />}
        {screen.name === 'prep' && <Prep key={screen.packId} packId={screen.packId} />}
        {screen.name === 'interview' && (
          <Interview
            pack={screen.pack}
            onExit={() => go({ name: 'setup' }, '#/')}
            onReview={(sessionId) => go({ name: 'review', sessionId }, `#/review/${sessionId}`)}
          />
        )}
        {screen.name === 'review' && (
          <Review
            key={screen.sessionId}
            sessionId={screen.sessionId}
            onStart={(pack) => go({ name: 'interview', pack }, '#/interview')}
          />
        )}
      </main>
    </div>
  )
}
