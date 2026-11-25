import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type Ref } from 'react'
import type { TurnVoice, VoiceSection } from '../api'
import { audioContext, loadBuffer, Playback, releaseBuffer, stopAllVoice } from './engine'
import { buildBlocks, columnPeaks, isSpeechColumn, speechFloor, type PeakBlocks, type Peaks } from './peaks'
import { gridlines, pitchRuns, yRangeOf } from './pitchPath'
import { fitView, fmtClock, MIN_SPAN_MS, msOfX, panView, revealMs, tickStepMs, ticksIn, xOfMs, zoomView, clampView, type View } from './scale'
import { extendSel, normSel, selectionReadout, selectionStats, type Sel } from './selection'
import { wordIndexAt } from './words'

/** Canvas layout in CSS pixels. */
const LEFT = 38
const RIGHT = 8
const WAVE_H = 60
const GAP = 8
const PITCH_H = 150
const AXIS_H = 22
const HEIGHT = WAVE_H + GAP + PITCH_H + AXIS_H
const TAG_H = 15

export interface VoiceGraphHandle {
  /** Move the playhead (and keep playing from there if it was playing). */
  seek: (ms: number) => void
  /** Select a range on the graph and play it (looped when Loop is on). */
  playRange: (startMs: number, endMs: number) => void
}

interface Props {
  audioUrl: string
  track: TurnVoice
  /** Flat stretches, WAV time; numbered "Flat 1..n" by start time. */
  sections: VoiceSection[]
  /** Force the pitch axis (used to draw an old and a new answer on one scale). */
  yRange?: [number, number]
  ariaLabel: string
  /** Called when playback starts, so the page can pause its video. */
  onPlayStart?: () => void
  /** The word being said changed (index into track.words, -1 for none). */
  onWord?: (i: number) => void
  ref?: Ref<VoiceGraphHandle>
}

interface Audio {
  buf: AudioBuffer
  samples: Float32Array
  blocks: PeakBlocks
  floor: number
  norm: number
}

interface Tokens {
  fg: string
  muted: string
  line: string
  band: string
  bg: string
}

const readTokens = (): Tokens => {
  const cs = getComputedStyle(document.documentElement)
  const g = (n: string, d: string) => cs.getPropertyValue(n).trim() || d
  return { fg: g('--text', '#0a0a0a'), muted: g('--muted', '#71717a'), line: g('--border-strong', '#d4d4d8'), band: g('--surface-3', '#e9e9eb'), bg: g('--surface', '#ffffff') }
}

function hatchPattern(g: CanvasRenderingContext2D, color: string): CanvasPattern | null {
  const t = document.createElement('canvas')
  t.width = t.height = 8
  const p = t.getContext('2d')
  if (!p) return null
  p.strokeStyle = color
  p.globalAlpha = 0.6
  p.lineWidth = 1.2
  p.beginPath()
  p.moveTo(-1, 9)
  p.lineTo(9, -1)
  p.moveTo(-1, 1)
  p.lineTo(1, -1)
  p.moveTo(7, 9)
  p.lineTo(9, 7)
  p.stroke()
  return g.createPattern(t, 'repeat')
}

type Gesture =
  | { kind: 'press'; x: number; y: number; ms: number; shift: boolean; moved: boolean }
  | { kind: 'select'; anchor: number }
  | { kind: 'handle'; fixed: number }
  | { kind: 'pinch'; d0: number; span0: number; anchor: number }
  | null

export default function VoiceGraph({ audioUrl, track, sections, yRange, ariaLabel, onPlayStart, onWord, ref }: Props) {
  const total = Math.max(1, track.duration_ms)
  const wrap = useRef<HTMLDivElement>(null)
  const staticCv = useRef<HTMLCanvasElement>(null)
  const overlayCv = useRef<HTMLCanvasElement>(null)
  const [w, setW] = useState(640)
  const [view, setView] = useState<View>(() => fitView(total))
  const [sel, setSel] = useState<Sel | null>(null)
  const [loop, setLoop] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [pos, setPos] = useState(0)
  const [audio, setAudio] = useState<Audio | null>(null)
  const [audioErr, setAudioErr] = useState<string | null>(null)
  const [theme, setTheme] = useState(0)

  const posRef = useRef(0)
  const live = useRef({ view, sel, loop, w })
  live.current = { view, sel, loop, w }
  const pbRef = useRef<Playback | null>(null)
  const toRef = useRef<number | null>(null)
  const followRef = useRef(true)
  const lastWord = useRef(-2)
  const tokens = useRef<Tokens | null>(null)
  const tagRects = useRef<{ x0: number; x1: number; sec: VoiceSection }[]>([])
  const ptrs = useRef(new Map<number, { x: number; y: number }>())
  const gesture = useRef<Gesture>(null)
  const anchorRef = useRef<number | null>(null)
  const peakCache = useRef(new Map<string, Peaks>())
  const cbs = useRef({ onPlayStart, onWord })
  cbs.current = { onPlayStart, onWord }

  const sorted = useMemo(() => [...sections].sort((a, b) => a.start_ms - b.start_ms), [sections])
  const runs = useMemo(() => pitchRuns(track.pitch_st ?? []), [track.pitch_st])
  const yr = useMemo(() => yRange ?? yRangeOf(track.pitch_st ?? []), [yRange, track.pitch_st])
  const plotW = Math.max(50, w - LEFT - RIGHT)
  const zoomed = view.end - view.start < total - 1

  // ---- size ----
  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(Math.max(260, Math.floor(el.clientWidth))))
    ro.observe(el)
    setW(Math.max(260, Math.floor(el.clientWidth)))
    return () => ro.disconnect()
  }, [])
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setTheme((t) => t + 1)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  // ---- reset when the turn changes ----
  useEffect(() => {
    setView(fitView(total))
    setSel(null)
    setPos(0)
    posRef.current = 0
    lastWord.current = -2
  }, [track, total])

  // ---- audio ----
  useEffect(() => {
    let dead = false
    setAudio(null)
    setAudioErr(null)
    peakCache.current.clear()
    loadBuffer(audioUrl).then(
      (buf) => {
        if (dead) return
        const samples = buf.getChannelData(0)
        const blocks = buildBlocks(samples)
        let norm = 0
        for (let i = 0; i < blocks.max.length; i++) norm = Math.max(norm, Math.abs(blocks.max[i]), Math.abs(blocks.min[i]))
        setAudio({ buf, samples, blocks, floor: speechFloor(blocks), norm: Math.max(norm, 0.01) })
      },
      (e: Error) => !dead && setAudioErr(e.message),
    )
    return () => {
      dead = true
      pbRef.current?.stop(true)
      pbRef.current = null
      releaseBuffer(audioUrl)
    }
  }, [audioUrl])

  // ---- words ----
  const reportWord = useCallback(
    (ms: number) => {
      const i = wordIndexAt(track.words, ms)
      if (i !== lastWord.current) {
        lastWord.current = i
        cbs.current.onWord?.(i)
      }
    },
    [track.words],
  )

  // ---- static layer ----
  useEffect(() => {
    const cv = staticCv.current
    if (!cv) return
    const dpr = window.devicePixelRatio || 1
    cv.width = Math.round(w * dpr)
    cv.height = Math.round(HEIGHT * dpr)
    const g = cv.getContext('2d')
    if (!g) return
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.clearRect(0, 0, w, HEIGHT)
    const t = readTokens()
    tokens.current = t
    const x = (ms: number) => xOfMs(ms, view, LEFT, plotW)
    const pitchTop = WAVE_H + GAP
    const pitchBottom = pitchTop + PITCH_H
    const [lo, hi] = yr
    const y = (st: number) => pitchTop + ((hi - st) / (hi - lo)) * PITCH_H
    g.font = '10px system-ui, sans-serif'
    g.textBaseline = 'middle'

    // waveform
    const mid = WAVE_H / 2
    g.fillStyle = t.line
    g.fillRect(LEFT, mid, plotW, 1)
    if (audio) {
      const cols = Math.floor(plotW)
      const key = `${cols}|${Math.round(view.start)}|${Math.round(view.end)}`
      let pk = peakCache.current.get(key)
      if (!pk) {
        pk = columnPeaks(audio.samples, audio.blocks, audio.buf.sampleRate, view.start, view.end, cols)
        if (peakCache.current.size > 12) peakCache.current.clear()
        peakCache.current.set(key, pk)
      }
      const k = (mid / audio.norm) * 0.95
      g.fillStyle = t.fg
      for (let c = 0; c < cols; c++) {
        const top = mid - pk.max[c] * k
        const h = Math.max(1, (pk.max[c] - pk.min[c]) * k)
        g.globalAlpha = isSpeechColumn(pk, c, audio.floor) ? 1 : 0.3
        g.fillRect(LEFT + c, top, 1, h)
      }
      g.globalAlpha = 1
    }

    // usual band, gridlines
    if (track.usual) {
      const top = y(Math.min(hi, track.usual.p90_st))
      const bot = y(Math.max(lo, track.usual.p10_st))
      if (bot > top) {
        g.fillStyle = t.band
        g.globalAlpha = 0.8
        g.fillRect(LEFT, top, plotW, bot - top)
        g.globalAlpha = 1
        g.fillStyle = t.muted
        g.textAlign = 'left'
        g.fillText('your usual', LEFT + 4, Math.min(bot - 6, top + 8))
      }
    }
    g.textAlign = 'right'
    for (const v of gridlines(lo, hi)) {
      g.fillStyle = t.line
      g.globalAlpha = v === 0 ? 1 : 0.5
      g.fillRect(LEFT, Math.round(y(v)), plotW, 1)
      g.globalAlpha = 1
      g.fillStyle = t.muted
      g.fillText(`${v > 0 ? '+' : ''}${v}`, LEFT - 5, y(v))
    }
    g.textAlign = 'left'
    g.fillStyle = t.muted
    g.fillText('st', 6, pitchTop + 6)

    // pitch line, clipped to the plot
    g.save()
    g.beginPath()
    g.rect(LEFT, pitchTop, plotW, PITCH_H)
    g.clip()
    g.strokeStyle = t.fg
    g.lineWidth = 1.5
    g.lineJoin = 'round'
    g.lineCap = 'round'
    const fm = track.frame_ms || 30
    for (const run of runs) {
      const a = (run[0].i + 0.5) * fm
      const b = (run[run.length - 1].i + 0.5) * fm
      if (b < view.start || a > view.end) continue
      g.beginPath()
      run.forEach((p, n) => {
        const px = x((p.i + 0.5) * fm)
        if (n === 0) g.moveTo(px, y(p.st))
        else g.lineTo(px, y(p.st))
      })
      g.stroke()
    }
    g.restore()

    // flat stretches: hatch over both tracks, tag on top
    tagRects.current = []
    const hatch = hatchPattern(g, t.fg)
    sorted.forEach((s, n) => {
      const x0 = Math.max(LEFT, x(s.start_ms))
      const x1 = Math.min(LEFT + plotW, x(s.end_ms))
      if (x1 <= x0) return
      if (hatch) {
        g.fillStyle = hatch
        g.fillRect(x0, 0, x1 - x0, pitchBottom)
      }
      g.fillStyle = t.fg
      g.fillRect(x0, 0, 1, pitchBottom)
      g.fillRect(x1 - 1, 0, 1, pitchBottom)
      const label = `Flat ${n + 1}`
      const tw = g.measureText(label).width + 10
      g.fillStyle = t.bg
      g.fillRect(x0, 0, tw, TAG_H)
      g.strokeStyle = t.fg
      g.lineWidth = 1
      g.strokeRect(x0 + 0.5, 0.5, tw - 1, TAG_H - 1)
      g.fillStyle = t.fg
      g.textAlign = 'left'
      g.fillText(label, x0 + 5, TAG_H / 2 + 0.5)
      tagRects.current.push({ x0, x1: x0 + tw, sec: s })
    })

    // cut joins (only when the session clock is known)
    if (track.segments) {
      g.save()
      g.setLineDash([3, 3])
      g.strokeStyle = t.fg
      g.lineWidth = 1
      for (const j of track.joins ?? []) {
        if (j.wav_ms < view.start || j.wav_ms > view.end) continue
        const jx = Math.round(x(j.wav_ms)) + 0.5
        g.beginPath()
        g.moveTo(jx, 0)
        g.lineTo(jx, pitchBottom)
        g.stroke()
        g.setLineDash([])
        const label = `⋮ ${Math.max(1, Math.round(j.cut_ms / 1000))} s cut`
        const tw = g.measureText(label).width + 8
        g.fillStyle = t.bg
        g.fillRect(jx + 2, WAVE_H - 14, tw, 13)
        g.fillStyle = t.fg
        g.textAlign = 'left'
        g.fillText(label, jx + 6, WAVE_H - 7.5)
        g.setLineDash([3, 3])
      }
      g.restore()
    }

    // time axis
    g.textAlign = 'center'
    g.fillStyle = t.muted
    const step = tickStepMs(view.end - view.start, Math.max(3, Math.floor(plotW / 90)))
    for (const tk of ticksIn(view, step)) {
      const tx = x(tk)
      g.fillStyle = t.line
      g.fillRect(Math.round(tx), pitchBottom, 1, 4)
      g.fillStyle = t.muted
      g.fillText(fmtClock(tk), tx, pitchBottom + 13)
    }
  }, [w, plotW, view, track, sorted, runs, yr, audio, theme])

  // ---- overlay: selection and playhead ----
  const drawOverlay = useCallback(() => {
    const cv = overlayCv.current
    if (!cv) return
    const dpr = window.devicePixelRatio || 1
    const lw = live.current.w
    if (cv.width !== Math.round(lw * dpr) || cv.height !== Math.round(HEIGHT * dpr)) {
      cv.width = Math.round(lw * dpr)
      cv.height = Math.round(HEIGHT * dpr)
    }
    const g = cv.getContext('2d')
    if (!g) return
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.clearRect(0, 0, lw, HEIGHT)
    const t = tokens.current ?? readTokens()
    const { view: v, sel: s, loop: lp } = live.current
    const pw = Math.max(50, lw - LEFT - RIGHT)
    const bottom = WAVE_H + GAP + PITCH_H
    const px = (ms: number) => xOfMs(ms, v, LEFT, pw)
    g.save()
    g.beginPath()
    g.rect(LEFT - 4, 0, pw + 8, HEIGHT)
    g.clip()
    if (s) {
      const x0 = px(s.start)
      const x1 = px(s.end)
      g.fillStyle = t.fg
      g.globalAlpha = 0.1
      g.fillRect(x0, 0, x1 - x0, bottom)
      g.globalAlpha = 1
      g.strokeStyle = t.fg
      g.lineWidth = 2
      g.setLineDash(lp ? [5, 3] : [])
      g.strokeRect(x0, 1, x1 - x0, bottom - 2)
      g.setLineDash([])
      g.fillStyle = t.fg
      for (const hx of [x0, x1]) g.fillRect(hx - 3, bottom / 2 - 11, 6, 22)
      g.fillStyle = t.bg
      for (const hx of [x0, x1]) g.fillRect(hx - 1, bottom / 2 - 7, 2, 14)
    }
    const ph = px(posRef.current)
    if (ph >= LEFT - 2 && ph <= LEFT + pw + 2) {
      g.fillStyle = t.fg
      g.fillRect(ph - 1, 0, 2, bottom)
      g.beginPath()
      g.moveTo(ph - 5, 0)
      g.lineTo(ph + 5, 0)
      g.lineTo(ph, 6)
      g.fill()
    }
    g.restore()
  }, [])
  useEffect(() => {
    drawOverlay()
  }, [drawOverlay, sel, view, pos, loop, w, theme, playing])

  // ---- playback ----
  const startPlayback = useCallback(
    async (fromMs: number, toMs: number | null, opts: { loop?: boolean } = {}) => {
      if (!audio) return
      pbRef.current?.stop(true)
      pbRef.current = null
      stopAllVoice()
      cbs.current.onPlayStart?.()
      await audioContext().resume()
      const lv = live.current
      const useLoop = opts.loop ?? lv.loop
      const loopR = useLoop ? (lv.sel ? { start: lv.sel.start / 1000, end: lv.sel.end / 1000 } : { start: 0, end: audio.buf.duration }) : null
      let from = fromMs
      if (loopR && (from / 1000 < loopR.start || from / 1000 >= loopR.end)) from = loopR.start * 1000
      const pb = new Playback(audio.buf, {
        from: from / 1000,
        to: toMs != null ? toMs / 1000 : undefined,
        loop: loopR,
        onEnd: (p, natural) => {
          if (pbRef.current !== pb) return
          pbRef.current = null
          setPlaying(false)
          const ms = natural ? (toMs ?? total) : p * 1000
          posRef.current = ms
          setPos(ms)
        },
      })
      pbRef.current = pb
      toRef.current = toMs
      followRef.current = true
      setPlaying(true)
    },
    [audio, total],
  )

  const pause = useCallback(() => {
    const pb = pbRef.current
    if (!pb) return
    const p = pb.stop(true) * 1000
    pbRef.current = null
    setPlaying(false)
    posRef.current = p
    setPos(p)
  }, [])

  useEffect(() => {
    if (!playing) return
    let id = 0
    const tick = () => {
      const pb = pbRef.current
      if (pb) {
        const ms = pb.pos() * 1000
        posRef.current = ms
        reportWord(ms)
        if (followRef.current) {
          const nv = revealMs(live.current.view, total, ms)
          if (nv !== live.current.view) setView(nv)
        }
        drawOverlay()
      }
      id = requestAnimationFrame(tick)
    }
    id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [playing, drawOverlay, reportWord, total])

  const seek = useCallback(
    (ms: number) => {
      const m = Math.min(total, Math.max(0, ms))
      posRef.current = m
      setPos(m)
      reportWord(m)
      followRef.current = true
      setView((v) => revealMs(v, total, m))
      if (pbRef.current) void startPlayback(m, toRef.current)
    },
    [total, reportWord, startPlayback],
  )

  const playRange = useCallback(
    (start: number, end: number) => {
      const s = normSel(start, end, total)
      setSel(s)
      posRef.current = start
      setPos(start)
      reportWord(start)
      setView((v) => revealMs(v, total, start))
      // `live.sel` is only updated on the next render, so pass the range through a one-shot override.
      live.current = { ...live.current, sel: s }
      void startPlayback(start, end)
    },
    [total, reportWord, startPlayback],
  )

  useImperativeHandle(ref, () => ({ seek, playRange }), [seek, playRange])

  const togglePlay = () => {
    if (playing) return pause()
    const at = posRef.current >= total - 50 ? 0 : posRef.current
    void startPlayback(at, null)
  }
  const toggleLoop = () => {
    const next = !loop
    setLoop(next)
    if (pbRef.current) void startPlayback(posRef.current, toRef.current, { loop: next })
  }
  const zoomBy = (factor: number) => {
    followRef.current = false
    setView((v) => zoomView(v, total, factor, Math.min(v.end, Math.max(v.start, posRef.current))))
  }
  const fit = () => setView(fitView(total))

  // ---- pointer ----
  const local = (e: { clientX: number; clientY: number }) => {
    const r = overlayCv.current!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  const msAt = (x: number) => Math.min(total, Math.max(0, msOfX(x, live.current.view, LEFT, plotW)))

  const onPointerDown = (e: ReactPointerEvent) => {
    wrap.current?.focus({ preventScroll: true })
    const p = local(e)
    ptrs.current.set(e.pointerId, p)
    e.currentTarget.setPointerCapture(e.pointerId)
    anchorRef.current = null
    if (ptrs.current.size === 2) {
      const [a, b] = [...ptrs.current.values()]
      gesture.current = { kind: 'pinch', d0: Math.max(10, Math.hypot(a.x - b.x, a.y - b.y)), span0: live.current.view.end - live.current.view.start, anchor: msOfX((a.x + b.x) / 2, live.current.view, LEFT, plotW) }
      return
    }
    const s = live.current.sel
    if (s) {
      const v = live.current.view
      const x0 = xOfMs(s.start, v, LEFT, plotW)
      const x1 = xOfMs(s.end, v, LEFT, plotW)
      if (Math.abs(p.x - x0) <= 8) return void (gesture.current = { kind: 'handle', fixed: s.end })
      if (Math.abs(p.x - x1) <= 8) return void (gesture.current = { kind: 'handle', fixed: s.start })
    }
    gesture.current = { kind: 'press', x: p.x, y: p.y, ms: msAt(p.x), shift: e.shiftKey, moved: false }
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    if (!ptrs.current.has(e.pointerId)) return
    const p = local(e)
    ptrs.current.set(e.pointerId, p)
    const gs = gesture.current
    if (!gs) return
    if (gs.kind === 'pinch' && ptrs.current.size >= 2) {
      const [a, b] = [...ptrs.current.values()]
      const d = Math.max(10, Math.hypot(a.x - b.x, a.y - b.y))
      const midX = (a.x + b.x) / 2
      followRef.current = false
      const span = Math.min(total, Math.max(Math.min(MIN_SPAN_MS, total), gs.span0 / (d / gs.d0)))
      const start = gs.anchor - ((midX - LEFT) / plotW) * span
      setView(clampView({ start, end: start + span }, total))
      return
    }
    if (gs.kind === 'press') {
      if (Math.abs(p.x - gs.x) >= 4) {
        gesture.current = { kind: 'select', anchor: gs.ms }
        setSel(normSel(gs.ms, msAt(p.x), total))
      }
    } else if (gs.kind === 'select') {
      setSel(normSel(gs.anchor, msAt(p.x), total))
    } else if (gs.kind === 'handle') {
      setSel(normSel(gs.fixed, msAt(p.x), total))
    }
  }

  const onPointerUp = (e: ReactPointerEvent) => {
    const p = local(e)
    ptrs.current.delete(e.pointerId)
    const gs = gesture.current
    if (ptrs.current.size === 0) gesture.current = null
    if (!gs) return
    if (gs.kind === 'press') {
      // a click: a flat tag plays that stretch, shift extends the selection, anything else seeks
      const tag = p.y <= TAG_H ? tagRects.current.find((r) => p.x >= r.x0 && p.x <= r.x1) : undefined
      if (tag) return playRange(tag.sec.start_ms, tag.sec.end_ms)
      const ms = msAt(p.x)
      if (gs.shift) {
        const next = extendSel(live.current.sel, ms, total, posRef.current)
        setSel(next)
        return
      }
      seek(ms)
    }
  }

  const onPointerCancel = (e: ReactPointerEvent) => {
    ptrs.current.delete(e.pointerId)
    if (ptrs.current.size === 0) gesture.current = null
  }

  // ---- wheel: ctrl/cmd zooms around the pointer, horizontal scroll pans when zoomed ----
  useEffect(() => {
    const el = overlayCv.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      const v = live.current.view
      const isZoomed = v.end - v.start < total - 1
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const r = el.getBoundingClientRect()
        const anchor = msOfX(e.clientX - r.left, v, LEFT, plotW)
        followRef.current = false
        setView(zoomView(v, total, Math.exp(-e.deltaY * 0.01), Math.min(total, Math.max(0, anchor))))
      } else if (isZoomed && (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey)) {
        e.preventDefault()
        followRef.current = false
        const d = e.deltaX || e.deltaY
        setView(panView(v, total, (d / plotW) * (v.end - v.start)))
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [plotW, total])

  // ---- keyboard ----
  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    const k = e.key
    const step = e.altKey ? 5000 : 1000
    const dir = k === 'ArrowRight' ? 1 : k === 'ArrowLeft' ? -1 : 0
    let handled = true
    if (dir) {
      const next = Math.min(total, Math.max(0, posRef.current + dir * step))
      if (e.shiftKey) {
        if (anchorRef.current == null) anchorRef.current = live.current.sel ? (dir > 0 ? live.current.sel.start : live.current.sel.end) : posRef.current
        setSel(normSel(anchorRef.current, next, total))
        posRef.current = next
        setPos(next)
        reportWord(next)
        setView((v) => revealMs(v, total, next))
      } else {
        anchorRef.current = null
        seek(next)
      }
    } else if (k === 'PageDown' || k === 'PageUp') {
      seek(posRef.current + (k === 'PageDown' ? 5000 : -5000))
    } else if (k === 'Home') seek(0)
    else if (k === 'End') seek(total)
    else if (k === ' ') togglePlay()
    else if (k === 'l' || k === 'L') toggleLoop()
    else if (k === 'Escape') {
      setSel(null)
      anchorRef.current = null
    } else if (k === '+' || k === '=') zoomBy(1.5)
    else if (k === '-' || k === '_') zoomBy(1 / 1.5)
    else if (k === '0') fit()
    else handled = false
    if (handled) e.preventDefault()
  }

  // ---- overview strip (when zoomed) ----
  const overviewMove = (e: ReactPointerEvent) => {
    if (e.buttons === 0 && e.pointerType === 'mouse') return
    const r = e.currentTarget.getBoundingClientRect()
    const centre = ((e.clientX - r.left) / r.width) * total
    followRef.current = false
    setView((v) => panView(v, total, centre - (v.start + v.end) / 2))
  }

  const stats = useMemo(() => (sel ? selectionStats(track.pitch_st ?? [], track.frame_ms || 30, sel.start, sel.end) : null), [sel, track])
  const wi = wordIndexAt(track.words, pos)
  const valueText = `${fmtClock(pos)}${wi >= 0 && track.words ? `, saying '${track.words[wi].w}'` : ''}`

  return (
    <div className="vg">
      <div
        ref={wrap}
        className="vg-plot"
        role="slider"
        tabIndex={0}
        aria-label={ariaLabel}
        aria-orientation="horizontal"
        aria-valuemin={0}
        aria-valuemax={Math.round(total / 1000)}
        aria-valuenow={Math.round(pos / 1000)}
        aria-valuetext={valueText}
        aria-keyshortcuts="ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight Alt+ArrowLeft Alt+ArrowRight Home End Space L Escape + - 0"
        style={{ height: HEIGHT }}
        onKeyDown={onKeyDown}
      >
        <canvas ref={staticCv} style={{ width: w, height: HEIGHT }} />
        <canvas
          ref={overlayCv}
          className="vg-overlay"
          style={{ width: w, height: HEIGHT }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerCancel}
        />
      </div>
      {zoomed && (
        <div className="vg-overview" onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); overviewMove(e) }} onPointerMove={overviewMove} aria-hidden>
          <div className="vg-overview-box" style={{ left: `${(view.start / total) * 100}%`, width: `${((view.end - view.start) / total) * 100}%` }} />
        </div>
      )}
      <div className="vg-controls">
        <button className="small" onClick={() => seek(posRef.current - 5000)} disabled={!audio}>
          ◀◀ 5 s
        </button>
        <button className="small primary" onClick={togglePlay} disabled={!audio} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <button className="small" onClick={() => sel && playRange(sel.start, sel.end)} disabled={!audio || !sel}>
          ▶ Selection
        </button>
        <button className={`small ${loop ? 'on' : ''}`} onClick={toggleLoop} aria-pressed={loop} disabled={!audio}>
          ⟲ Loop
        </button>
        <span className="vg-spacer" />
        <button className="small" onClick={() => zoomBy(1 / 1.5)} disabled={!zoomed} aria-label="Zoom out">
          −
        </button>
        <button className="small" onClick={() => zoomBy(1.5)} disabled={view.end - view.start <= Math.min(MIN_SPAN_MS, total) + 1} aria-label="Zoom in">
          +
        </button>
        <button className="small" onClick={fit} disabled={!zoomed}>
          Fit
        </button>
      </div>
      <p className="vg-readout small" aria-live="polite">
        {audioErr ? (
          <span className="muted">{audioErr}</span>
        ) : !audio ? (
          <span className="muted">Loading audio…</span>
        ) : sel && stats ? (
          selectionReadout(sel, stats)
        ) : (
          <span className="muted">
            {fmtClock(pos)} of {fmtClock(total)} · click to seek, drag to select, Shift+click to extend{zoomed ? '' : ', Ctrl/⌘+scroll to zoom'}
          </span>
        )}
      </p>
      <p className="vg-legend muted small" aria-hidden>
        <span><i className="sw speech" /> speech</span>
        <span><i className="sw usual" /> your usual</span>
        <span><i className="sw flat" /> flat</span>
        <span>⋮ cut</span>
        <span>▏playhead</span>
      </p>
    </div>
  )
}
