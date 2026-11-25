export type InterviewType = 'behavioural' | 'technical' | 'mixed' | 'case' | 'roleplay'
export type Stage = 'screen' | 'full' | 'final'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Style = 'friendly' | 'neutral' | 'tough'

export interface PackOptions {
  interview_type: InterviewType
  stage: Stage
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
  | { type: 'transcript'; text: string; stt_ms: number | null; turn_idx: number }
  | {
      type: 'sentence'
      index: number
      turn_idx: number
      text: string
      expressions: Expression[]
      audio_wav_base64: string | null
      duration_ms: number
      word_timings: WordTiming[]
      tts_error: string | null
    }
  | {
      type: 'done'
      turn_idx: number | null
      reply_text: string
      expressions: Expression[]
      is_final: boolean
      timings: { first_sentence_ms: number | null; total_ms: number }
    }
  | { type: 'error'; message: string }

export interface TurnTiming {
  turn_idx: number
  t_start_ms: number | null
  t_end_ms: number | null
}

export interface Turn {
  idx: number
  speaker: 'interviewer' | 'candidate'
  text: string
  expressions: Expression[]
  t_start_ms: number | null
  t_end_ms: number | null
}

export type ReportStatus = 'pending' | 'ready' | 'error' | 'none'

export interface SessionInfo {
  id: string
  pack_id: string
  started_at: number
  ended_at: number | null
  overall_score: number | null
  has_recording: boolean
  pack: Pack | null
  turns: Turn[]
  report_status: ReportStatus | null
}

export interface SessionListItem {
  id: string
  pack_id: string
  pack_title: string
  role: string
  company: string
  started_at: number
  ended_at: number | null
  overall_score: number | null
  report_status: ReportStatus | null
}

export const CATEGORY_LABEL: Record<string, string> = {
  intro: 'Intro',
  motivation: 'Motivation',
  behavioural: 'Behavioural',
  technical: 'Technical',
  case: 'Case',
  roleplay: 'Role-play',
  logistics: 'Logistics',
  other: 'Other',
}

export type Criterion = 'relevance' | 'structure' | 'specificity' | 'evidence'

export interface AnswerFeedback {
  question_turn: number | null
  question: string
  category: string
  competency: string
  answer_summary: string
  scores: Record<Criterion, number>
  average: number
  better_answer: string
  tips: string[]
}

export interface Report {
  overall_score: number
  summary: string
  answers: AnswerFeedback[]
  filler_words: { count: number; examples: string[]; by_word: Record<string, number> }
  avg_answer_seconds: number | null
  top_fixes: string[]
  previous_fixes?: { fix: string; status: 'improved' | 'partly' | 'not_yet' | 'not_tested'; evidence: string }[]
}

export interface ReportResponse {
  status: ReportStatus
  report: Report | null
  report_md: string | null
  error: string | null
}

export interface HistorySession {
  id: string
  pack_id: string
  started_at: number
  ended_at: number | null
  overall_score: number | null
  has_recording: number | boolean
  report_status: ReportStatus | null
  criteria: Record<Criterion, number> | null
  filler_count: number | null
  avg_answer_seconds: number | null
  answers: number | null
  partial: boolean
  by_category: Record<string, { average: number; answers: number }>
}

export interface PackHistory {
  pack: Pack
  sessions: HistorySession[]
  last_used: number
}

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
  extractPdfText: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/extract-text', { method: 'POST', body: form })
    if (!res.ok) throw await errorFrom(res)
    return ((await res.json()) as { text: string }).text
  },
  listPacks: () => request<Pack[]>('/packs'),
  getPack: (id: string) => request<Pack>(`/packs/${id}`),
  updatePack: (id: string, pack: PackInput) =>
    request<Pack>(`/packs/${id}`, { method: 'PUT', body: JSON.stringify(pack) }),
  deletePack: (id: string) => request<{ deleted: string }>(`/packs/${id}`, { method: 'DELETE' }),
  history: () => request<PackHistory[]>('/history'),
  packHistory: (id: string) => request<HistorySession[]>(`/packs/${id}/history`),
  deleteSession: (id: string) => request<{ deleted: string }>(`/sessions/${id}`, { method: 'DELETE' }),
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
  endSession: (sessionId: string, timeline: TurnTiming[] = [], score = true) =>
    request<{ ended: boolean }>(`/sessions/${sessionId}/end`, {
      method: 'POST',
      body: JSON.stringify({ timeline, score }),
    }),
  uploadRecording: async (sessionId: string, blob: Blob) => {
    const form = new FormData()
    form.append('recording', blob, 'recording.webm')
    const res = await fetch(`/api/sessions/${sessionId}/recording`, { method: 'POST', body: form })
    if (!res.ok) throw await errorFrom(res)
    return (await res.json()) as { bytes: number }
  },
  listSessions: (limit = 10) => request<SessionListItem[]>(`/sessions?limit=${limit}`),
  getSession: (sessionId: string) => request<SessionInfo>(`/sessions/${sessionId}`),
  getReport: (sessionId: string) => request<ReportResponse>(`/sessions/${sessionId}/report`),
  regenerateReport: (sessionId: string) =>
    request<{ status: ReportStatus }>(`/sessions/${sessionId}/report`, { method: 'POST' }),
  recordingUrl: (sessionId: string, download = false) =>
    `/api/sessions/${sessionId}/recording${download ? '?download=1' : ''}`,
  reportMdUrl: (sessionId: string) => `/api/sessions/${sessionId}/report.md`,
}
