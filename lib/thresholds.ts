// User-set price levels: the band edges that drive colour, and the two trade
// triggers that drive signals.
//
// These live in the URL rather than a database. There is no login on this
// dashboard, so a per-user row has nowhere to hang; a URL carries the whole
// configuration, survives a reload, and can be pasted to someone else with the
// levels intact.

export interface Thresholds {
  /** Below this is cheap enough to buy/charge. */
  chargeBelow: number
  /** Above this is dear enough to sell/discharge. */
  dischargeAbove: number
  /** Band edge: normal → elevated. */
  elevated: number
  /** Band edge: elevated → scarcity. */
  scarcity: number
  /** Band edge: scarcity → extreme. */
  extreme: number
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  chargeBelow: 15,
  dischargeAbove: 80,
  elevated: 50,
  scarcity: 100,
  extreme: 1000,
}

/** Short URL keys, so a configured link stays readable. */
const KEYS: Record<keyof Thresholds, string> = {
  chargeBelow: 'cb',
  dischargeAbove: 'da',
  elevated: 'el',
  scarcity: 'sc',
  extreme: 'ex',
}

export const FIELDS: Array<{
  key: keyof Thresholds
  urlKey: string
  label: string
  hint: string
  max: number
}> = [
  { key: 'chargeBelow', urlKey: 'cb', label: 'charge below', hint: 'buy / charge signal', max: 200 },
  { key: 'dischargeAbove', urlKey: 'da', label: 'discharge above', hint: 'sell / discharge signal', max: 500 },
  { key: 'elevated', urlKey: 'el', label: 'elevated', hint: 'amber band starts', max: 500 },
  { key: 'scarcity', urlKey: 'sc', label: 'scarcity', hint: 'red band starts', max: 2000 },
  { key: 'extreme', urlKey: 'ex', label: 'extreme', hint: 'top band starts', max: 5000 },
]

const MIN = -500
const MAX = 5000

function one(raw: string | undefined, fallback: number): number {
  if (raw === undefined) return fallback
  const n = Number(raw)
  // Reject rather than clamp a nonsense value: silently substituting a level
  // the user did not choose would mis-colour every price on the page and give
  // no clue why.
  if (!Number.isFinite(n) || n < MIN || n > MAX) return fallback
  return n
}

/**
 * Read levels from URL params, falling back per-field.
 *
 * The band edges are forced into ascending order. Out-of-order edges would make
 * a band unreachable — with scarcity below elevated, nothing is ever "elevated"
 * — and a colour that can never appear is worse than a corrected one.
 */
export function readThresholds(params: Record<string, string | undefined>): Thresholds {
  const t: Thresholds = {
    chargeBelow: one(params[KEYS.chargeBelow], DEFAULT_THRESHOLDS.chargeBelow),
    dischargeAbove: one(params[KEYS.dischargeAbove], DEFAULT_THRESHOLDS.dischargeAbove),
    elevated: one(params[KEYS.elevated], DEFAULT_THRESHOLDS.elevated),
    scarcity: one(params[KEYS.scarcity], DEFAULT_THRESHOLDS.scarcity),
    extreme: one(params[KEYS.extreme], DEFAULT_THRESHOLDS.extreme),
  }
  t.scarcity = Math.max(t.scarcity, t.elevated)
  t.extreme = Math.max(t.extreme, t.scarcity)
  return t
}

/** Only non-default levels, so a default configuration keeps a clean URL. */
export function thresholdParams(t: Thresholds): Record<string, string> {
  const out: Record<string, string> = {}
  for (const field of FIELDS) {
    if (t[field.key] !== DEFAULT_THRESHOLDS[field.key]) {
      out[field.urlKey] = String(t[field.key])
    }
  }
  return out
}

export function isDefault(t: Thresholds): boolean {
  return FIELDS.every((f) => t[f.key] === DEFAULT_THRESHOLDS[f.key])
}
