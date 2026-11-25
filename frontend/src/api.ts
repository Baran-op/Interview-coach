import type { SpeechSegment } from './audio/vad'
import type { FaceStats } from './face/stats'
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
  t_listen_ms?: number | null
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

export interface VoiceStats {
  pitch_range_st: number | null
  loudness_range_db: number | null
  trail_off_pct: number | null
  voiced_s: number
}

export type VoiceFlag = 'flat' | 'lively' | 'trailing'

/** The voice part of a delivery object; absent on reports written before voice stats existed. */
export interface VoiceDelivery {
  voice?: VoiceStats | null
  voice_flags?: VoiceFlag[]
  voice_usual?: Pick<VoiceStats, 'pitch_range_st' | 'loudness_range_db' | 'trail_off_pct'> | null
}

export const VOICE_FLAG_LABEL: Record<VoiceFlag, string> = { flat: 'flat', lively: 'lively', trailing: 'trailing off' }

/** "pitch range 3.1 st (your usual 5.4) · trails off in 45% of phrases (usual 20%)", or '' with no voice stats. */
export function voiceTooltip(d: VoiceDelivery): string {
  const v = d.voice
  if (!v) return ''
  const u = d.voice_usual
  const parts: string[] = []
  if (v.pitch_range_st != null) parts.push(`pitch range ${v.pitch_range_st.toFixed(1)} st` + (u?.pitch_range_st != null ? ` (your usual ${u.pitch_range_st.toFixed(1)})` : ''))
  if (v.trail_off_pct != null) parts.push(`trails off in ${Math.round(v.trail_off_pct)}% of phrases` + (u?.trail_off_pct != null ? ` (usual ${Math.round(u.trail_off_pct)}%)` : ''))
  return parts.join(' · ')
}

export interface FaceMoment {
  kind: 'down' | 'away' | 'still'
  start_ms: number
  end_ms: number
  /** What you were saying (about 15 words); absent for typed answers and older sessions. */
  quote?: string
}

export interface FaceStatsSummary {
  on_screen_pct: number | null
  looked_down_pct: number | null
  expressiveness: number | null
  face_found_pct: number | null
  frames: number
  t_start_ms: number
  t_end_ms: number
  moments?: FaceMoment[]
}

export type FaceFlag = 'looking_down' | 'low_eye_contact' | 'still'

/** The face part of a delivery object; absent on reports written before face stats existed, or with no camera. */
export interface FaceDelivery {
  face?: FaceStatsSummary | null
  face_flags?: FaceFlag[]
  face_usual?: { expressiveness: number | null } | null
}

export const FACE_FLAG_LABEL: Record<FaceFlag, string> = {
  looking_down: 'mostly looking down',
  low_eye_contact: 'low eye contact',
  still: 'still face',
}
export const FACE_MOMENT_LABEL: Record<FaceMoment['kind'], string> = { down: 'Looked down', away: 'Looked away', still: 'Still face' }

/** "looked down 35% of the answer · expressiveness 2.0 (your usual 5.0)", or '' with no face stats. */
export function faceTooltip(d: FaceDelivery): string {
  const f = d.face
  if (!f) return ''
  const parts: string[] = []
  if (f.on_screen_pct != null) parts.push(`on screen ${Math.round(f.on_screen_pct)}% of the answer`)
  if (f.looked_down_pct != null) parts.push(`looked down ${Math.round(f.looked_down_pct)}%`)
  if (f.expressiveness != null) {
    const u = d.face_usual?.expressiveness
    parts.push(`expressiveness ${f.expressiveness.toFixed(1)}` + (u != null ? ` (your usual ${u.toFixed(1)})` : ''))
  }
  return parts.join(' · ')
}

export interface AnswerDelivery extends VoiceDelivery, FaceDelivery {
  seconds: number
  first_answer_seconds: number
  wpm: number | null
  fillers: number
  hedges: number
  i_count: number
  we_count: number
  numbers: number
  pauses_over_1s: number | null
  target: [number, number] | null
  flag: 'short' | 'long' | null
}

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
  delivery?: AnswerDelivery
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

export interface PrepStory {
  title: string
  competencies: string[]
  situation: string
  task: string
  action: string
  result: string
  numbers: string[]
}

export interface PrepSheet {
  likely_questions: { question: string; category: string; why: string }[]
  gaps: { requirement: string; cv_evidence: string | null; how_to_address: string }[]
  stories: PrepStory[]
  questions_to_ask: string[]
}

export interface PrepResponse {
  prep: PrepSheet | null
  created_at?: number
  /** True when the JD, CV or company notes changed since the sheet was written. */
  stale?: boolean
}

export type DrillSource = 'starter' | 'report' | 'prep' | 'custom'

export interface DrillQuestion {
  key: string
  question: string
  category: string | null
  source: DrillSource
  attempts: number
  latest: number | null
  best: number | null
}

export interface DrillResult {
  scores: Record<Criterion, number>
  average: number
  tips: string[]
  improved: string[]
  better_answer: string
  delivery?: (Record<string, unknown> & { seconds?: number | null }) & VoiceDelivery & FaceDelivery
}

export interface DrillAttempt {
  id: string
  pack_id: string
  question_key: string
  question: string
  category: string | null
  answer_text: string
  seconds: number | null
  has_audio: boolean
  result: DrillResult | null
  created_at: number
}

export interface TtsSentence {
  text: string
  audio_wav_base64: string | null
  word_timings: WordTiming[]
  expressions: Expression[]
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
  research: (company: string, role: string, jd: string) =>
    request<{ notes: string; sources: string[] }>('/research', {
      method: 'POST',
      body: JSON.stringify({ company, role, jd }),
    }),
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
  sendText: (sessionId: string, text: string, face?: FaceStats | null) =>
    streamEvents(`/sessions/${sessionId}/turn`, {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(face ? { text, face } : { text }),
    }),
  sendAudio: (sessionId: string, wav: Blob, face?: FaceStats | null, segments?: SpeechSegment[]) => {
    const form = new FormData()
    form.append('audio', wav, 'answer.wav')
    if (face) form.append('face', JSON.stringify(face))
    if (segments?.length) form.append('segments', JSON.stringify(segments))
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
  getPrep: (packId: string) => request<PrepResponse>(`/packs/${packId}/prep`),
  /** One Claude request. */
  writePrep: (packId: string) => request<PrepResponse>(`/packs/${packId}/prep`, { method: 'POST' }),
  drillQuestions: (packId: string) => request<{ questions: DrillQuestion[] }>(`/packs/${packId}/drill`),
  drillAttempts: (packId: string, key: string) =>
    request<{ attempts: DrillAttempt[] }>(`/packs/${packId}/drill/attempts?key=${encodeURIComponent(key)}`),
  /** One Claude request. Typed answer (`text`) or a spoken one (`wav` plus its length in seconds). */
  drillAttempt: async (
    packId: string,
    a: { question: string; category: string | null; text?: string; wav?: Blob; seconds?: number; face?: FaceStats | null; segments?: SpeechSegment[] },
  ) => {
    const path = `/packs/${packId}/drill/attempts`
    if (a.wav) {
      const form = new FormData()
      form.append('audio', a.wav, 'answer.wav')
      form.append('question', a.question)
      form.append('category', a.category ?? '')
      if (a.seconds) form.append('seconds', String(a.seconds))
      if (a.face) form.append('face', JSON.stringify(a.face))
      if (a.segments?.length) form.append('segments', JSON.stringify(a.segments))
      const res = await fetch(`/api${path}`, { method: 'POST', body: form })
      if (!res.ok) throw await errorFrom(res)
      return (await res.json()) as { attempt: DrillAttempt; previous: DrillAttempt | null }
    }
    return request<{ attempt: DrillAttempt; previous: DrillAttempt | null }>(path, {
      method: 'POST',
      body: JSON.stringify({ question: a.question, category: a.category ?? '', text: a.text, seconds: a.seconds }),
    })
  },
  tts: (text: string, voice?: string) =>
    request<{ sentences: TtsSentence[] }>('/tts', { method: 'POST', body: JSON.stringify({ text, voice }) }),
  recordingUrl: (sessionId: string, download = false) =>
    `/api/sessions/${sessionId}/recording${download ? '?download=1' : ''}`,
  reportMdUrl: (sessionId: string) => `/api/sessions/${sessionId}/report.md`,
}
