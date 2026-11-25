// Which candidate turns make up each answer (mirrors delivery.answer_turns in the backend), and the Drill "from" parameter. Pure.

export interface TurnLite {
  idx: number
  speaker: 'interviewer' | 'candidate'
  text: string
  t_start_ms?: number | null
  t_end_ms?: number | null
  has_audio?: boolean
}

export interface TurnRef<T extends TurnLite = TurnLite> {
  turn: T
  /** The first candidate turn after the question is the main answer; later ones are follow-ups. */
  kind: 'main' | 'followup'
  /** 0 for the main answer, 1.. for follow-ups. */
  n: number
  /** The interviewer's follow-up question (the interviewer turn just before this one); null for the main answer. */
  prompt: string | null
}

export interface QuestionEntry<T extends TurnLite = TurnLite> {
  key: string
  /** Index into report.answers, or null when grouped by turn (no report yet). */
  answerIdx: number | null
  question: string
  turns: TurnRef<T>[]
}

function refsFor<T extends TurnLite>(mine: T[], all: T[]): TurnRef<T>[] {
  return mine.map((t, n) => {
    const before = all.filter((x) => x.speaker === 'interviewer' && x.idx < t.idx).pop()
    return { turn: t, kind: n === 0 ? 'main' : 'followup', n, prompt: n === 0 ? null : (before?.text ?? null) }
  })
}

/** One entry per report answer: the candidate turns after its question turn and before the next answer's. */
export function questionsFromReport<T extends TurnLite>(answers: { question_turn: number | null; question: string }[], turns: T[]): QuestionEntry<T>[] {
  const starts = answers.map((a) => a.question_turn).filter((q): q is number => typeof q === 'number').sort((a, b) => a - b)
  return answers.map((a, i) => {
    const qt = a.question_turn
    const next = typeof qt === 'number' ? starts.find((s) => s > qt) : undefined
    const mine = typeof qt === 'number' ? turns.filter((t) => t.speaker === 'candidate' && t.idx > qt && (next === undefined || t.idx < next)) : []
    return { key: `a${i}`, answerIdx: i, question: a.question, turns: refsFor(mine, turns) }
  })
}

/** Before the report exists: every candidate turn on its own, titled by the interviewer turn before it. */
export function questionsByTurn<T extends TurnLite>(turns: T[]): QuestionEntry<T>[] {
  return turns
    .filter((t) => t.speaker === 'candidate')
    .map((t) => {
      const before = turns.filter((x) => x.speaker === 'interviewer' && x.idx < t.idx).pop()
      return { key: `t${t.idx}`, answerIdx: null, question: before?.text ?? 'Your answer', turns: [{ turn: t, kind: 'main' as const, n: 0, prompt: null }] }
    })
}

/** Index of the entry that contains candidate turn `idx`, or -1. */
export const questionOfTurn = (qs: QuestionEntry[], idx: number) => qs.findIndex((q) => q.turns.some((t) => t.turn.idx === idx))

export interface From {
  session: string
  turn: number
  section: string | null
}

/** Drill's `from=<session>~<turn>~<section>` (the section is optional). */
export function parseFrom(raw: string | null | undefined): From | null {
  if (!raw) return null
  const [session, turn, section] = raw.split('~')
  const n = Number(turn)
  if (!session || !/^[\w-]+$/.test(session) || turn === undefined || turn === '' || !Number.isInteger(n) || n < 0) return null
  return { session, turn: n, section: section || null }
}

export const fromParam = (session: string, turn: number, section?: string | null) => `${session}~${turn}${section ? `~${section}` : ''}`
