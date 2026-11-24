export type InterviewType = 'behavioural' | 'technical' | 'mixed' | 'case'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Style = 'friendly' | 'neutral' | 'tough'

export interface PackOptions {
  interview_type: InterviewType
  num_questions: number
  minutes: number | null
  difficulty: Difficulty
  style: Style
  interviewer_name: string
  voice: string
}

export interface PackInput {
  title: string
  role: string
  company: string
  jd: string
  profile: string
  company_notes: string
  options: PackOptions
}

export interface Pack extends PackInput {
  id: string
  created_at: number
}

export interface Expression {
  tag: string
  char_index: number
}

export interface WordTiming {
  word: string
  start_ms: number
  end_ms: number
}

/** Events streamed (NDJSON) by POST /sessions and POST /sessions/{id}/turn. */
export type InterviewEvent =
  | { type: 'session'; session_id: string }
  | { type: 'transcript'; text: string; stt_ms: number | null }
  | {
      type: 'sentence'
      index: number
      text: string
      expressions: Expression[]
      audio_wav_base64: string | null
      duration_ms: number
      word_timings: WordTiming[]
      tts_error: string | null
    }
  | {
      type: 'done'
      reply_text: string
      expressions: Expression[]
      is_final: boolean
      timings: { first_sentence_ms: number | null; total_ms: number }
    }
  | { type: 'error'; message: string }

export interface ModelState {
  model: string
  status: 'not loaded' | 'loading' | 'loaded' | 'unavailable'
  error: string | null
}

export interface Health {
  ok: boolean
  problems: string[]
  whisper: ModelState
  kokoro: ModelState
  voice_ready: boolean
}

async function errorFrom(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null)
  const detail = body?.detail ?? body?.problems?.join(' ') ?? res.statusText
  const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  ;(err as Error & { status?: number }).status = res.status
  return err
}

/** POST and yield each line of the NDJSON response as it arrives. */
async function* streamEvents(path: string, init: RequestInit): AsyncGenerator<InterviewEvent> {
  const res = await fetch(`/api${path}`, { method: 'POST', ...init })
  if (!res.ok || !res.body) throw await errorFrom(res)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (value) buf += value
    let nl: number
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (line) yield JSON.parse(line) as InterviewEvent
    }
    if (done) break
  }
  if (buf.trim()) yield JSON.parse(buf) as InterviewEvent
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw await errorFrom(res)
  return (await res.json()) as T
}

export const api = {
  health: async (): Promise<Health> => {
    const res = await fetch('/api/health')
    if (!res.ok && res.status !== 503) throw new Error('Backend not reachable on :8000')
    return res.json()
  },
  listPacks: () => request<Pack[]>('/packs'),
  createPack: (pack: PackInput) =>
    request<Pack>('/packs', { method: 'POST', body: JSON.stringify(pack) }),
  voices: () => request<{ default: string; voices: string[] }>('/voices'),
  startSession: (packId: string) =>
    streamEvents('/sessions', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pack_id: packId }),
    }),
  sendText: (sessionId: string, text: string) =>
    streamEvents(`/sessions/${sessionId}/turn`, {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),
  sendAudio: (sessionId: string, wav: Blob) => {
    const form = new FormData()
    form.append('audio', wav, 'answer.wav')
    return streamEvents(`/sessions/${sessionId}/turn`, { body: form })
  },
  endSession: (sessionId: string) =>
    request<{ ended: boolean }>(`/sessions/${sessionId}/end`, { method: 'POST' }),
}
