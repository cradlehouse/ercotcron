// Price presentation primitives: the colour scale, $/MWh formatting, clocks.
//
// ERCOT energy prices are $/MWh. They go negative when there is more wind and
// solar on the system than load (generators pay to stay online), sit in the
// $20-40 band most hours, and can run to the $5000 offer cap during scarcity.
// A linear colour ramp would waste its whole range on the normal band, so the
// scale is banded instead: the bands are the operationally meaningful ones.

export const ERCOT_TZ = 'America/Chicago'

/** Band edges in $/MWh. */
export const NEGATIVE_BELOW = 0
export const ELEVATED_ABOVE = 50
export const SCARCITY_ABOVE = 100
export const EXTREME_ABOVE = 1000

export type Tone = 'unknown' | 'negative' | 'normal' | 'elevated' | 'scarcity' | 'extreme'

export interface ToneStyle {
  tone: Tone
  /** Short operator-facing label. */
  label: string
  /** Tailwind class for the number itself. */
  text: string
  /** Tailwind class for a card / chip background. */
  bg: string
  /** Tailwind class for a card / chip border. */
  border: string
  /** Raw hex, for inline SVG where Tailwind classes do not reach. */
  hex: string
}

const STYLES: Record<Tone, ToneStyle> = {
  unknown: {
    tone: 'unknown',
    label: 'no data',
    text: 'text-zinc-600',
    bg: 'bg-zinc-900/40',
    border: 'border-line',
    hex: '#4b5563',
  },
  negative: {
    tone: 'negative',
    label: 'negative',
    text: 'text-sky-300',
    bg: 'bg-sky-500/10',
    border: 'border-sky-500/30',
    hex: '#38bdf8',
  },
  normal: {
    tone: 'normal',
    label: 'normal',
    text: 'text-emerald-300',
    bg: 'bg-emerald-500/[0.06]',
    border: 'border-emerald-500/20',
    hex: '#34d399',
  },
  elevated: {
    tone: 'elevated',
    label: 'elevated',
    text: 'text-amber-300',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    hex: '#fbbf24',
  },
  scarcity: {
    tone: 'scarcity',
    label: 'scarcity',
    text: 'text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-red-500/35',
    hex: '#f87171',
  },
  extreme: {
    tone: 'extreme',
    label: 'extreme',
    text: 'text-red-200',
    bg: 'bg-red-600/25',
    border: 'border-red-500/60',
    hex: '#ef4444',
  },
}

/** Band edges. Defaults here; the user's own levels come from lib/thresholds. */
export interface Bands {
  elevated: number
  scarcity: number
  extreme: number
}

const DEFAULT_BANDS: Bands = {
  elevated: ELEVATED_ABOVE,
  scarcity: SCARCITY_ABOVE,
  extreme: EXTREME_ABOVE,
}

export function toneOf(price: number | null | undefined, bands: Bands = DEFAULT_BANDS): Tone {
  if (price === null || price === undefined || !Number.isFinite(price)) return 'unknown'
  if (price < NEGATIVE_BELOW) return 'negative'
  if (price >= bands.extreme) return 'extreme'
  if (price >= bands.scarcity) return 'scarcity'
  if (price >= bands.elevated) return 'elevated'
  return 'normal'
}

export function styleFor(
  price: number | null | undefined,
  bands: Bands = DEFAULT_BANDS,
): ToneStyle {
  return STYLES[toneOf(price, bands)]
}

/** Legend entries for a given set of band edges. */
export function scaleFor(bands: Bands): ReadonlyArray<{ tone: Tone; range: string }> {
  return [
    { tone: 'negative', range: `< $${NEGATIVE_BELOW}` },
    { tone: 'normal', range: `$0 – $${bands.elevated}` },
    { tone: 'elevated', range: `$${bands.elevated} – $${bands.scarcity}` },
    { tone: 'scarcity', range: `$${bands.scarcity} – $${bands.extreme}` },
    { tone: 'extreme', range: `> $${bands.extreme}` },
  ]
}

export function styleForTone(tone: Tone): ToneStyle {
  return STYLES[tone]
}

/** The scale, in band order — for a legend. */
export const SCALE: ReadonlyArray<{ tone: Tone; range: string }> = [
  { tone: 'negative', range: `< $${NEGATIVE_BELOW}` },
  { tone: 'normal', range: `$0 – $${ELEVATED_ABOVE}` },
  { tone: 'elevated', range: `$${ELEVATED_ABOVE} – $${SCARCITY_ABOVE}` },
  { tone: 'scarcity', range: `$${SCARCITY_ABOVE} – $${EXTREME_ABOVE}` },
  { tone: 'extreme', range: `> $${EXTREME_ABOVE}` },
]

// ------------------------------------------------------------------ numbers --

/**
 * PostgREST usually hands back `numeric` as a JSON number, but a driver or a
 * view cast can turn it into a string. Normalise before doing arithmetic on it,
 * because `"-12.5" < 0` is false and would silently mis-colour a negative price.
 */
export function num(value: unknown): number | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed === '') return null
    const parsed = Number(trimmed)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function int(value: unknown): number {
  const n = num(value)
  return n === null ? 0 : Math.round(n)
}

/** `$32.14`, `-$8.90`, `$5,000.00`. Em dash when there is nothing to show. */
export function formatUsd(price: number | null | undefined, digits = 2): string {
  if (price === null || price === undefined || !Number.isFinite(price)) return '—'
  const sign = price < 0 ? '-' : ''
  const body = Math.abs(price).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  return `${sign}$${body}`
}

/** Compact axis label: `$5k`, `$120`, `-$8`. */
export function formatAxis(price: number): string {
  const sign = price < 0 ? '-' : ''
  const abs = Math.abs(price)
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(abs >= 10000 ? 0 : 1)}k`
  if (abs >= 100) return `${sign}$${abs.toFixed(0)}`
  return `${sign}$${abs.toFixed(abs < 10 ? 1 : 0)}`
}

export function formatCount(value: unknown): string {
  const n = num(value)
  return n === null ? '—' : Math.round(n).toLocaleString('en-US')
}

export function formatRatio(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits)}×`
}

/** Seconds as `4.2s`, `3m 10s`, `2h 06m`. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const sign = seconds < 0 ? '-' : ''
  const s = Math.abs(seconds)
  if (s < 60) return `${sign}${s < 10 ? s.toFixed(1) : s.toFixed(0)}s`
  if (s < 3600) return `${sign}${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, '0')}s`
  return `${sign}${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}

// -------------------------------------------------------------------- times --

export function toMillis(value: string | number | Date | null | undefined): number | null {
  if (value === null || value === undefined) return null
  const ms = value instanceof Date ? value.getTime() : new Date(value).getTime()
  return Number.isFinite(ms) ? ms : null
}

/** `18s ago`, `4m ago`, `3h 12m ago`, `2d ago`, `in 45m`. */
export function formatRelative(
  value: string | number | Date | null | undefined,
  now: number = Date.now(),
): string {
  const ms = toMillis(value)
  if (ms === null) return '—'
  const delta = now - ms
  const ahead = delta < 0
  const s = Math.abs(delta) / 1000
  let body: string
  if (s < 5) return 'just now'
  if (s < 60) body = `${Math.round(s)}s`
  else if (s < 3600) body = `${Math.floor(s / 60)}m`
  else if (s < 86400) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    body = m ? `${h}h ${m}m` : `${h}h`
  } else body = `${Math.floor(s / 86400)}d`
  return ahead ? `in ${body}` : `${body} ago`
}

const timeFmt = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})

const dateTimeFmt = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})

/** `14:45` in ERCOT local time — the only clock a Texas grid operator reads. */
export function formatTime(value: string | number | Date | null | undefined): string {
  const ms = toMillis(value)
  return ms === null ? '—' : timeFmt.format(new Date(ms))
}

/** `Jul 26, 14:45` in ERCOT local time. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const ms = toMillis(value)
  return ms === null ? '—' : dateTimeFmt.format(new Date(ms)).replace(',', '')
}

/** ISO string for a query bound, N hours back from now. */
export function hoursAgoIso(hours: number, now: number = Date.now()): string {
  return new Date(now - hours * 3600_000).toISOString()
}
