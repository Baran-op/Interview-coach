import { useEffect, useState } from 'react'
import { api, type Pack } from './api'
import Setup from './pages/Setup'
import Interview from './pages/Interview'
import Review from './pages/Review'

type Screen = { name: 'setup' } | { name: 'interview'; pack: Pack } | { name: 'review'; sessionId: string }

// Tiny hash router: #/ (setup), #/interview, #/review/<session id>.
function fromHash(current: Screen): Screen {
  const hash = window.location.hash
  const review = hash.match(/^#\/review\/([\w-]+)/)
  if (review) return { name: 'review', sessionId: review[1] }
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
      </header>
      {healthProblems.length > 0 && (
        <div className="banner error">
          {healthProblems.map((p) => (
            <div key={p}>{p}</div>
          ))}
        </div>
      )}
      <main>
        {screen.name === 'setup' && <Setup onStart={(pack) => go({ name: 'interview', pack }, '#/interview')} />}
        {screen.name === 'interview' && (
          <Interview
            pack={screen.pack}
            onExit={() => go({ name: 'setup' }, '#/')}
            onReview={(sessionId) => go({ name: 'review', sessionId }, `#/review/${sessionId}`)}
          />
        )}
        {screen.name === 'review' && <Review key={screen.sessionId} sessionId={screen.sessionId} />}
      </main>
    </div>
  )
}
