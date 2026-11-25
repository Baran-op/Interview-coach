// Waveform peaks: min/max per pixel column from decoded samples. Pure.

export const BLOCK = 64

export interface PeakBlocks {
  block: number
  min: Float32Array
  max: Float32Array
}

/** Min and max of every `block` samples, built once per decoded turn. */
export function buildBlocks(samples: Float32Array, block = BLOCK): PeakBlocks {
  const n = Math.ceil(samples.length / block)
  const min = new Float32Array(n)
  const max = new Float32Array(n)
  for (let b = 0; b < n; b++) {
    let lo = Infinity
    let hi = -Infinity
    const end = Math.min(samples.length, (b + 1) * block)
    for (let i = b * block; i < end; i++) {
      const v = samples[i]
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
    min[b] = lo
    max[b] = hi
  }
  return { block, min, max }
}

export interface Peaks {
  min: Float32Array
  max: Float32Array
}

/** Peaks for `cols` pixel columns covering [startMs, endMs). Columns outside the audio are 0. Uses the block summary when a column spans many samples. */
export function columnPeaks(samples: Float32Array, blocks: PeakBlocks, rate: number, startMs: number, endMs: number, cols: number): Peaks {
  const min = new Float32Array(cols)
  const max = new Float32Array(cols)
  const perMs = rate / 1000
  const span = endMs - startMs
  const B = blocks.block
  for (let c = 0; c < cols; c++) {
    const s0 = Math.floor((startMs + (c / cols) * span) * perMs)
    const s1 = Math.max(s0 + 1, Math.floor((startMs + ((c + 1) / cols) * span) * perMs))
    if (s1 <= 0 || s0 >= samples.length) continue
    let lo = Infinity
    let hi = -Infinity
    const a = Math.max(0, s0)
    const z = Math.min(samples.length, s1)
    const scan = (from: number, to: number) => {
      for (let i = from; i < to; i++) {
        const v = samples[i]
        if (v < lo) lo = v
        if (v > hi) hi = v
      }
    }
    if (z - a >= B * 2) {
      const b0 = Math.ceil(a / B)
      const b1 = Math.floor(z / B)
      scan(a, b0 * B)
      for (let b = b0; b < b1; b++) {
        if (blocks.min[b] < lo) lo = blocks.min[b]
        if (blocks.max[b] > hi) hi = blocks.max[b]
      }
      scan(b1 * B, z)
    } else {
      scan(a, z)
    }
    if (lo <= hi) {
      min[c] = lo
      max[c] = hi
    }
  }
  return { min, max }
}

/** Amplitude below which a column counts as silence: 10% of the 98th percentile of block amplitudes. */
export function speechFloor(blocks: PeakBlocks): number {
  const amps: number[] = []
  for (let i = 0; i < blocks.min.length; i++) amps.push(Math.max(Math.abs(blocks.min[i]), Math.abs(blocks.max[i])))
  if (amps.length === 0) return 0
  amps.sort((a, b) => a - b)
  return amps[Math.min(amps.length - 1, Math.floor(amps.length * 0.98))] * 0.1
}

export const isSpeechColumn = (p: Peaks, c: number, floor: number) => Math.max(Math.abs(p.min[c]), Math.abs(p.max[c])) > floor
