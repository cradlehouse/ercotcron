// Shared money formatters for the member pages.
//
// Only genuinely-common behavior lives here; pages with deliberately
// different formatting (string-coercing usd on /bids, compact signed money
// on the record page) keep their own local helpers.

/** Absolute whole dollars, thousands-grouped: usd(-1234.5) => "$1,234.5". */
export const usd = (v: number) => `$${Math.abs(v).toLocaleString()}`

/** Signed dollars with a true minus sign: signed(-5) => "−$5". */
export const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(v)}`

/** Fixed-decimal dollars, em-dash when missing: usdFixed(3.5) => "$3.50". */
export const usdFixed = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : `$${v.toFixed(dp)}`
