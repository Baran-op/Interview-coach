import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { api, type Expression, type Pack } from '../api'

interface Message {
  speaker: 'interviewer' | 'candidate'
  text: string
  expressions?: Expression[]
}

interface Props {
  pack: Pack
  onExit: () => void
}

function formatTime(ms: number) {
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export default function Interview({ pack, onExit }: Props) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(true)
  const [finished, setFinished] = useState(false)
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [now, setNow] = useState(Date.now())
  const started = useRef(false)
  const bottom = useRef<HTMLDivElement>(null)
  const interviewer = pack.options.interviewer_name || 'Interviewer'

  // Start once (StrictMode runs effects twice in dev).
  useEffect(() => {
    if (started.current) return
    started.current = true
    api
      .startSession(pack.id)
      .then((r) => {
        setSessionId(r.session_id)
        setStartedAt(Date.now())
        setMessages([{ speaker: 'interviewer', text: r.reply_text, expressions: r.expressions }])
        setFinished(r.is_final)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false))
  }, [pack.id])

  useEffect(() => {
    if (!startedAt || ended) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [startedAt, ended])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  const end = async () => {
    if (sessionId && !ended) {
      try {
        await api.endSession(sessionId)
      } catch (e) {
        setError((e as Error).message)
      }
    }
    setEnded(true)
  }

  // When the interviewer says [END], close the session automatically.
  useEffect(() => {
    if (finished && !ended) void end()
  }, [finished])

  const send = async () => {
    const text = draft.trim()
    if (!text || !sessionId || busy || finished) return
    setDraft('')
    setError(null)
    setMessages((m) => [...m, { speaker: 'candidate', text }])
    setBusy(true)
    try {
      const r = await api.sendTurn(sessionId, text)
      setMessages((m) => [...m, { speaker: 'interviewer', text: r.reply_text, expressions: r.expressions }])
      setFinished(r.is_final)
    } catch (e) {
      setError((e as Error).message)
      setDraft(text) // let me retry without retyping
      setMessages((m) => m.slice(0, -1))
    } finally {
      setBusy(false)
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className="interview card">
      <div className="interview-bar">
        <span>
          {pack.role || pack.title}
          {pack.company ? ` · ${pack.company}` : ''}
        </span>
        <span className="timer">{startedAt ? formatTime(now - startedAt) : '0:00'}</span>
        {!ended ? (
          <button className="danger" onClick={() => void end()} disabled={!sessionId}>
            End interview
          </button>
        ) : (
          <button onClick={onExit}>Back to setup</button>
        )}
      </div>

      <div className="chat">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.speaker}`}>
            <div className="who">{m.speaker === 'interviewer' ? interviewer : 'You'}</div>
            <div className="bubble">{m.text}</div>
            {m.expressions && m.expressions.length > 0 && (
              <div className="tags">
                {m.expressions.map((x, j) => (
                  <span key={j} className="tag" title={`at char ${x.char_index}`}>
                    {x.tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg interviewer muted">{interviewer} is thinking…</div>}
        {ended && <div className="banner">Interview ended. Feedback reports arrive in Milestone 3.</div>}
        <div ref={bottom} />
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="composer">
        <textarea
          rows={4}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder={finished || ended ? 'Interview finished' : 'Type your answer… (Ctrl/⌘+Enter to send)'}
          disabled={finished || ended || !sessionId}
          autoFocus
        />
        <button className="primary" onClick={() => void send()} disabled={busy || finished || ended || !draft.trim()}>
          Send
        </button>
      </div>
    </div>
  )
}
