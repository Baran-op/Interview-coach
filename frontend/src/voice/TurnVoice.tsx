import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { TurnVoice as TurnVoiceData, VoiceSection } from '../api'
import VoiceGraph, { type VoiceGraphHandle } from './VoiceGraph'
import { unionRange, yRangeOf } from './pitchPath'
import { fmtClock } from './scale'
import { joinWords, wavToSession, wordsInRange } from './words'

/**
 * Flat stretches are labelled "provisional" until the thresholds are calibrated on real recordings (PLAN-voice V3).
 * Flip to false when V3 is ticked.
 */
export const FLAT_PROVISIONAL = true

type Load = { state: 'loading' } | { state: 'error'; message: string; missing: boolean } | { state: 'ready'; data: TurnVoiceData }

async function fetchVoice(url: string): Promise<TurnVoiceData> {
  const res = await fetch(url)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const err = new Error(typeof body?.detail === 'string' ? body.detail : res.statusText) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return (await res.json()) as TurnVoiceData
}

function useVoice(url: string | undefined): Load | null {
  const [load, setLoad] = useState<Load | null>(url ? { state: 'loading' } : null)
  useEffect(() => {
    if (!url) {
      setLoad(null)
      return
    }
    let dead = false
    setLoad({ state: 'loading' })
    fetchVoice(url).then(
      (data) => !dead && setLoad({ state: 'ready', data }),
      (e: Error & { status?: number }) => !dead && setLoad({ state: 'error', message: e.message, missing: e.status === 404 }),
    )
    return () => {
      dead = true
    }
  }, [url])
  return load
}

/** The exact words of a stored section, from the turn's word offsets when we have them. */
export function sectionWords(s: VoiceSection, data: TurnVoiceData | null | undefined): string {
  const ws = wordsInRange(data?.words, s.start_ms, s.end_ms)
  if (ws.length) return joinWords(ws)
  if (Array.isArray(s.words)) return s.words.join(' ')
  return s.words ?? ''
}

interface Props {
  voiceUrl: string
  audioUrl: string
  /** Load this other turn too and draw both on one pitch scale (old interview answer vs new Drill attempt). */
  peerVoiceUrl?: string
  title: string
  /** Shown in place of a transcript when the audio has no word timings. */
  fallbackText?: string
  /** The report's stored copies of this turn's sections; their advice is used when the route's copy has none. */
  storedSections?: VoiceSection[]
  /** "(usual 4.2)" in each flat card header. */
  usualWindowSt?: number | null
  /** Why a stretch has no advice (provisional, lower priority, report written before voice advice); null hides the line. */
  noAdviceNote?: string | null
  /** The link behind "Try again in Drill"; null hides it. */
  drillHref?: (sectionId: string | null) => string | null
  onPlayStart?: () => void
  /** How many flat stretches this turn has, once loaded. */
  onSections?: (n: number) => void
  /** What a missing graph says when the route is not there (Drill attempts before the backend routes exist). */
  unavailableText?: string
}

/** One turn: its graph, transcript with word highlight, and flat-stretch cards. Empty states are short muted lines. */
export default function TurnVoice({ voiceUrl, audioUrl, peerVoiceUrl, title, fallbackText, storedSections, usualWindowSt, noAdviceNote, drillHref, onPlayStart, onSections, unavailableText }: Props) {
  const load = useVoice(voiceUrl)
  const peer = useVoice(peerVoiceUrl)
  const handle = useRef<VoiceGraphHandle>(null)
  const [word, setWord] = useState(-1)
  const data = load?.state === 'ready' ? load.data : null

  const sections = useMemo(() => {
    if (!data) return []
    return [...(data.sections ?? [])]
      .sort((a, b) => a.start_ms - b.start_ms)
      .map((s) => ({ ...s, advice: s.advice ?? storedSections?.find((x) => x.id === s.id)?.advice ?? null }))
  }, [data, storedSections])
  useEffect(() => {
    if (data) onSections?.(sections.length)
  }, [data, sections.length, onSections])

  const header = (
    <h4 className="vt-title">
      {title}
      {data?.segments?.length ? (
        <span className="muted">
          {' '}
          · {fmtClock(data.segments[0].start_ms)}–{fmtClock(data.segments[data.segments.length - 1].end_ms)} in the interview
        </span>
      ) : data && !data.reason ? (
        <span className="muted"> · audio time</span>
      ) : null}
    </h4>
  )

  if (!load || load.state === 'loading')
    return (
      <div className="vt">
        {header}
        <p className="muted small">Loading…</p>
      </div>
    )
  if (load.state === 'error') {
    return (
      <div className="vt">
        {header}
        <p className="muted small">{load.missing ? (unavailableText ?? 'No audio was saved for this answer.') : `Could not load the voice data: ${load.message}`}</p>
      </div>
    )
  }

  const d = load.data
  if (d.reason === 'typed') {
    return (
      <div className="vt">
        {header}
        <p className="muted small">You typed this answer, so there&apos;s no audio to analyse.</p>
        {fallbackText && <p className="vt-text small">{fallbackText}</p>}
      </div>
    )
  }
  if (d.reason === 'no_audio') {
    return (
      <div className="vt">
        {header}
        <p className="muted small">{unavailableText ?? 'No audio was saved for this answer.'}</p>
        {fallbackText && <p className="vt-text small">{fallbackText}</p>}
      </div>
    )
  }

  const peerData = peer?.state === 'ready' && !peer.data.reason ? peer.data : null
  const yRange = peerData ? unionRange(yRangeOf(d.pitch_st ?? []), yRangeOf(peerData.pitch_st ?? [])) : undefined
  const words = d.words
  const inFlat = (i: number) => !!words && sections.some((s) => (words[i].start_ms + words[i].end_ms) / 2 >= s.start_ms && (words[i].start_ms + words[i].end_ms) / 2 <= s.end_ms)

  return (
    <div className="vt">
      {header}
      {d.reason === 'too_short' && <p className="muted small">Too short to measure pitch range (under 8 s of speech).</p>}
      {!d.usual && d.reason !== 'too_short' && (
        <p className="muted small">Your usual range appears after 10 measured answers{d.baseline_n != null ? ` (${d.baseline_n} so far)` : ''}.</p>
      )}
      <VoiceGraph ref={handle} audioUrl={audioUrl} track={d} sections={sections} yRange={yRange} ariaLabel={`${title}: pitch and waveform`} onPlayStart={onPlayStart} onWord={setWord} />

      {words && words.length > 0 ? (
        <p className="vt-text">
          {words.map((w, i) => (
            <Fragment key={i}>
              <span
                className={`vt-word ${word === i ? 'now' : ''} ${inFlat(i) ? 'flat' : ''}`}
                onClick={() => handle.current?.seek(w.start_ms)}
              >
                {w.w}
              </span>{' '}
            </Fragment>
          ))}
        </p>
      ) : (
        <>
          <p className="muted small">{d.words_pending ? 'Finding word timings… (after the interview ends)' : "Word timings aren't available."}</p>
          {fallbackText && <p className="vt-text small">{fallbackText}</p>}
        </>
      )}

      {sections.map((s, n) => (
        <FlatCard
          key={s.id}
          n={n + 1}
          s={s}
          data={d}
          usual={usualWindowSt}
          noAdviceNote={noAdviceNote}
          href={drillHref?.(s.id) ?? null}
          onHear={() => handle.current?.playRange(s.start_ms, s.end_ms)}
        />
      ))}
      {peerData && <p className="muted small">The old and new graphs share one pitch scale.</p>}
    </div>
  )
}

function FlatCard({ n, s, data, usual, noAdviceNote, href, onHear }: { n: number; s: VoiceSection; data: TurnVoiceData; usual?: number | null; noAdviceNote?: string | null; href: string | null; onHear: () => void }) {
  const said = sectionWords(s, data)
  const inSession = wavToSession(s.start_ms, data.segments)
  const a = s.advice
  const note: ReactNode = a ? null : noAdviceNote
  return (
    <div className="flat-card">
      <div className="flat-head">
        <strong>
          <i className="sw flat" /> Flat {n}
        </strong>
        <span>
          {fmtClock(s.start_ms)}–{fmtClock(s.end_ms)}
          {s.range_st != null && ` · ${s.range_st.toFixed(1)} st`}
          {usual != null && ` (usual ${usual.toFixed(1)})`}
        </span>
        {FLAT_PROVISIONAL && (
          <span className="chip" title="The thresholds for flat stretches are still being checked against real recordings.">
            provisional
          </span>
        )}
        {inSession != null && <span className="muted small">{fmtClock(inSession)} in the interview</span>}
      </div>
      <div className="actions">
        <button className="small" onClick={onHear}>
          ▶ Hear it
        </button>
        {href && (
          <a className="button-link small" href={href}>
            Try again in Drill ↗
          </a>
        )}
      </div>
      {said && (
        <p className="small">
          <span className="muted">Exactly what you said: </span>“{said}”
        </p>
      )}
      {a ? (
        <ul className="flat-advice small">
          {a.stress?.length > 0 && (
            <li>
              <strong>Stress</strong> <em>{a.stress.join(', ')}</em>
            </li>
          )}
          {a.say_it && (
            <li>
              <strong>Say it</strong> “{a.say_it}”
            </li>
          )}
          {a.why && (
            <li>
              <strong>Why</strong> {a.why}
            </li>
          )}
        </ul>
      ) : (
        note && <p className="muted small">{note}</p>
      )}
    </div>
  )
}
