// The one auction calendar. Every auction date, hour count, and label shown
// anywhere on the site (nav badge, landing, signup, bid sheet) derives from
// this module — never hand-type "Sep 8" in a component again.
//
// From ERCOT's CRR Activity Calendar (WMS-approved edition on file). October
// 2026 TOU hours are computed, not assumed (products.tou_of over the whole
// month): 22 weekdays x16, 9 weekend days x16, remainder off-peak; no NERC
// holiday in October and DST ends Nov 1, so 31 x 24 = 744 hours exactly.

export interface AuctionCalendar {
  name: string          // ERCOT's own auction name, e.g. 2026.OCT.Monthly.Auction
  opens: string         // ISO date bids open
  closes: string        // ISO date bids close (17:00 Central)
  deliveryStart: string // e.g. 10/1/2026 — goes into the CSV verbatim
  deliveryEnd: string
  deliveryLabel: string
  hours: Record<string, number>
}

export const AUCTION: AuctionCalendar = {
  name: '2026.OCT.Monthly.Auction',
  opens: '2026-09-08',
  closes: '2026-09-10',
  deliveryStart: '10/1/2026',
  deliveryEnd: '10/31/2026',
  deliveryLabel: '1–31 Oct 2026',
  hours: { PeakWD: 352, PeakWE: 144, 'Off-peak': 248 },
}

/** ERCOT posts results on or before this date (CRR Activity Calendar). */
export const RESULTS_DUE = '2026-09-17'

/** The auction after the current one — swapped into AUCTION when its
 *  valuation run publishes. Dates from ERCOT's CRR Activity Calendar:
 *  NOV bid window opens Oct 13 (12:01am), closes Oct 15 (5pm), results
 *  on or before Oct 22. NOV 2026 hours computed by ercot/calendar.py
 *  (Thanksgiving moves 16 hours from PeakWD to PeakWE). */
export const NEXT_AUCTION: AuctionCalendar = {
  name: '2026.NOV.Monthly.Auction',
  opens: '2026-10-13',
  closes: '2026-10-15',
  deliveryStart: '11/1/2026',
  deliveryEnd: '11/30/2026',
  deliveryLabel: '1–30 Nov 2026',
  hours: { PeakWD: 320, PeakWE: 160, 'Off-peak': 240 },
}
export const NEXT_MONTH = NEXT_AUCTION.name.split('.')[1] ?? ''

/** Where the cycle stands right now. */
export function phase(now: number = Date.now()): 'open' | 'awaiting-results' | 'between' {
  if (daysToClose(now) >= 0) return 'open'
  const due = new Date(`${RESULTS_DUE}T23:59:00-05:00`).getTime()
  return now <= due ? 'awaiting-results' : 'between'
}

/** 'OCT' — the delivery month, straight from ERCOT's auction name. */
export const AUCTION_MONTH = AUCTION.name.split('.')[1] ?? ''

const short = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })

/** 'Sep 8' — the day bids open. */
export const OPENS_LABEL = short(AUCTION.opens)

/** 'Sep 10' — the day bids close. */
export const CLOSES_LABEL = short(AUCTION.closes)

/** 'Sep 8–10' (or 'Sep 30 – Oct 2' across a month boundary). */
export const WINDOW_LABEL = (() => {
  const sameMonth = AUCTION.opens.slice(0, 7) === AUCTION.closes.slice(0, 7)
  return sameMonth
    ? `${OPENS_LABEL}–${Number(AUCTION.closes.slice(8, 10))}`
    : `${OPENS_LABEL} – ${CLOSES_LABEL}`
})()

/**
 * Whole days until bids close (17:00 Central on the close date).
 * 0 = closes today; negative = the window has passed.
 */
export function daysToClose(now: number = Date.now()): number {
  return Math.ceil(
    (new Date(`${AUCTION.closes}T17:00:00-05:00`).getTime() - now) / 86_400_000,
  )
}

/** 'bids open 2026-09-08 · close 2026-09-10 (2 days left) · delivery 1–31 Oct 2026' */
export function windowLine(daysLeft: number = daysToClose()): string {
  if (daysLeft >= 0) {
    return `bids open ${AUCTION.opens} · close ${AUCTION.closes} (${daysLeft} day${daysLeft === 1 ? '' : 's'} left) · delivery ${AUCTION.deliveryLabel}`
  }
  const nextShort = new Date(`${NEXT_AUCTION.opens}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
  return phase() === 'awaiting-results'
    ? `bids closed ${CLOSES_LABEL} · results post by ${short(RESULTS_DUE)} · ${NEXT_MONTH} bids open ${nextShort}`
    : `closed · ${NEXT_MONTH} sheet posts before its window opens ${nextShort}`
}
