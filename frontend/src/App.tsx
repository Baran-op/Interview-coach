import { useEffect, useState } from 'react'
import { api, type Pack } from './api'
import Setup from './pages/Setup'
import Interview from './pages/Interview'

type Screen = { name: 'setup' } | { name: 'interview'; pack: Pack }

export default function App() {
  const [screen, setScreen] = useState<Screen>({ name: 'setup' })
  const [healthProblems, setHealthProblems] = useState<string[]>([])

  useEffect(() => {
    api
      .health()
      .then((h) => setHealthProblems(h.problems))
      .catch((e: Error) => setHealthProblems([e.message]))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Interview Coach</span>
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
        {screen.name === 'setup' && (
          <Setup onStart={(pack) => setScreen({ name: 'interview', pack })} />
        )}
        {screen.name === 'interview' && (
          <Interview pack={screen.pack} onExit={() => setScreen({ name: 'setup' })} />
        )}
      </main>
    </div>
  )
}
