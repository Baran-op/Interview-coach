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

export interface InterviewerReply {
  session_id: string
  transcript: string | null
  reply_text: string
  expressions: Expression[]
  is_final: boolean
}

export interface Health {
  ok: boolean
  problems: string[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body?.detail ?? body?.problems?.join(' ') ?? res.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return body as T
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
  startSession: (packId: string) =>
    request<InterviewerReply>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ pack_id: packId }),
    }),
  sendTurn: (sessionId: string, text: string) =>
    request<InterviewerReply>(`/sessions/${sessionId}/turn`, {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  endSession: (sessionId: string) =>
    request<{ ended: boolean }>(`/sessions/${sessionId}/end`, { method: 'POST' }),
}
