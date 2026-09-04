'use client'
// The auction order ticket — what to bid, at what price, how many MW, by when.
//
// Client component by design: path_valuations is locked at the database (the
// valuations ARE the product), so the sheet is fetched through the
// authenticated-only get_bid_sheet() RPC with the signed-in user's session.
// Anonymous visitors get the MemberGate redirect and an empty shell — curl
// gets nothing.
//
// Private books: rows from a named holder's book (positions, prior bids) are
// shown only to users with an APPROVED claim on that holder code. Everyone
// else sees the market scan only, and their CSV carries their own code.
//
// Tiers:
//   green  = worth more than the auction has actually charged, on real
//            clearing history, no cautions — bid the shown price
//   amber  = positive value but unverifiable (never seen clearing) or
//            flagged — size small if at all
//   red    = the auction charges more than the path has returned, with the
//            clearing price SHOWN so the rejection argues for itself

import { useEffect, useState } from 'react'
import { Empty, ErrorNote, Panel } from '@/app/components'
import { num } from '@/lib/prices'
import { sb, type PathValuation } from '@/lib/supabase'
import { Ticket, type AuctionMeta, type TicketRow } from './ticket'

// From ERCOT's CRR Activity Calendar (WMS-approved edition on file). September
// 2026 TOU hours are computed, not assumed: Labor Day (7 Sep) is a NERC
// holiday, so its peak hours count as PeakWE — 21 weekdays x16, 9 weekend-rule
// days x16, remainder off-peak. Fixed constants drift a few percent by month,
// which is exactly the error the trader's own workbook carries.
const AUCTION: Omit<AuctionMeta, 'daysLeft' | 'holder'> = {
  name: '2026.SEP.Monthly.Auction',
  opens: '2026-08-11',
  closes: '2026-08-13',
  deliveryStart: '9/1/2026',
  deliveryEnd: '9/30/2026',
  deliveryLabel: '1–30 Sep 2026',
  hours: { PeakWD: 336, PeakWE: 144, 'Off-peak': 240 },
}

// Which holder code a private valuation book belongs to. Rows from these
// books are invisible without an approved claim on the code.
const BOOK_HOLDER: Record<string, string> = { 'Saaico 2027 First': 'XSAAIC' }

const MATERIALITY = 0.1 // ceilings below 10c are noise, not trades
// Never bid to breakeven: the limit is value/1.5, so a worst-case fill at the
// full limit still leaves ~50% expected margin. (Trader's rule, and doubly
// right here: our magnitude estimates are only ~61% within 2x.)
const REQUIRED_MARGIN = 1.5

function plainFlag(w: string | null): string {
  if (!w) return ''
  if (w.includes('fading')) return 'Congestion fading — recent months are far below the average this price is built on.'
  if (w.includes('spike')) return 'Pays rarely but big — expect long waits between payoffs.'
  if (w.includes('re-rated')) return `Grid changed near this path in the last 90 days (${w.split(':')[0]}) — history is less reliable.`
  if (w.includes('silent')) return `A driving constraint has gone quiet (${w.split(':')[0]}) — the congestion may be gone.`
  return w
}

function usd(v: number | string | null | undefined): string {
  const n = num(v)
  return n === null ? '—' : `$${n.toFixed(2)}`
}

type SheetPayload = {
  valuations: PathValuation[]
  offered: { source: string; sink: string; time_of_use: string; hedge_type: string; mw: number | string }[]
  offers_auction: string | null
  points: { name: string; active: boolean }[]
}

export default function BidsPage() {
  const [sheet, setSheet] = useState<SheetPayload | null>(null)
  const [owned, setOwned] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([sb.rpc('get_bid_sheet'), sb.rpc('my_claims')]).then(([s, c]) => {
      if (s.error) setError(s.error.message)
      else setSheet(s.data as SheetPayload)
      const claims = (c.data as { holder_code: string; status: string }[]) ?? []
      setOwned(new Set(claims.filter(x => x.status === 'approved').map(x => x.holder_code)))
      setLoading(false)
    })
  }, [])

  if (loading) {
    return <div className="p-6 text-sm text-[#7d9096]">loading the bid sheet…</div>
  }
  if (error || !sheet) {
    return <div className="p-6"><ErrorNote error={error ?? 'The sheet did not load — refresh, or sign in again.'} /></div>
  }

  const allRows = (sheet.valuations ?? []).filter(r => {
    const holder = BOOK_HOLDER[r.book]
    return holder === undefined || owned.has(holder)
  })
  const ownedHolder = Object.values(BOOK_HOLDER).find(h => owned.has(h)) ?? ''

  const offered = new Map<string, number>()
  for (const o of sheet.offered ?? []) {
    const k = `${o.source}|${o.sink}|${o.time_of_use}|${o.hedge_type}`
    offered.set(k, (offered.get(k) ?? 0) + (num(o.mw) ?? 0))
  }
  const active = new Set((sheet.points ?? []).filter(p => p.active).map(p => p.name))
  const daysLeft = Math.ceil(
    (new Date(`${AUCTION.closes}T17:00:00-05:00`).getTime() - Date.now()) / 86_400_000,
  )
  const auction: AuctionMeta = { ...AUCTION, daysLeft, holder: ownedHolder }

  const ticket: TicketRow[] = []
  const red: PathValuation[] = []
  const excluded: PathValuation[] = []
  const unpriced: PathValuation[] = []

  for (const r of allRows) {
    const rawCeiling = num(r.ceiling)
    const marginLimit = rawCeiling === null ? null : rawCeiling / REQUIRED_MARGIN
    const isScanRow = r.book === 'Market' || r.book === 'Discovery'
    const clearedEarly = num(r.cleared_price)
    // Cheap lottery paths: cap the limit at 3x the going rate. You are trying
    // to own a LOT of something at ~10c, not a little of it at any price.
    const ceiling = marginLimit !== null && isScanRow && clearedEarly !== null && clearedEarly < 0.5
      ? Math.min(marginLimit, Math.max(3 * clearedEarly, 0.1))
      : marginLimit
    const worth = num(r.value_mean)
    const cleared = num(r.cleared_price)
    const prevBid = num(r.bid_price)
    const prevMw = num(r.mw)
    const isDiscovery = r.book === 'Discovery'
    const isMarket = r.book === 'Market'
    if (worth === null || ceiling === null) {
      unpriced.push(r)
      continue
    }
    if (active.size > 0 && (!active.has(r.source) || !active.has(r.sink))) {
      excluded.push(r)
      continue
    }
    const marginX = cleared !== null && cleared > 0 ? ceiling / cleared : null
    const hasHistory = cleared !== null
    const flagged = Boolean(r.warnings)
    const overbid = prevBid !== null && prevBid > ceiling

    if (ceiling < MATERIALITY || (hasHistory && marginX !== null && marginX <= 1.0)) {
      red.push(r)
      continue
    }
    // Whole-market study (588k monthly BUY positions, 17 delivery months):
    // aggregate ROI by cleared price is +38% under 10c, +16-21% to 50c, +5.5%
    // to 75c, then negative-to-zero above 75c and -13% above $5. Expensive
    // paths are competitively bid and winner's-cursed; the durable edge lives
    // under ~75c. A high limit alone therefore never earns green: above 75c
    // demand a 2x margin, and above $5 the market's aggregate record is a loss.
    const px = cleared ?? ceiling
    const priceEdge =
      px < 0.75 ? 'cheap' : px <= 5 && marginX !== null && marginX >= 2.0 ? 'ok' : 'rich'
    const tier: TicketRow['tier'] =
      hasHistory && !flagged && marginX !== null && marginX > 1.05 && priceEdge !== 'rich'
        ? 'green' : 'amber'
    ticket.push({
      key: `${r.book}|${r.source}|${r.sink}|${r.time_of_use}|${r.hedge_type}`,
      origin: isMarket ? 'market' : isDiscovery ? 'discovery' : 'book',
      // Market-scan rows are ranked well but magnitude-unproven (July holdout:
      // top-50 beat clearing 64%, yet paid ~10% of annual-mean worth) — never
      // green until a bid has been validated end to end.
      tier: isMarket ? 'amber' : tier,
      source: r.source,
      sink: r.sink,
      tou: r.time_of_use,
      hedge: r.hedge_type,
      offeredMw: offered.get(`${r.source}|${r.sink}|${r.time_of_use}|${r.hedge_type}`) ?? null,
      ceiling,
      worth,
      cleared,
      marginX,
      pctHours: num(r.pct_hours_pos),
      prevBid: isDiscovery || isMarket ? null : prevBid,
      prevMw: isDiscovery || isMarket ? null : prevMw,
      // Lottery sizing (Tim's rule): on cheap high-margin paths, scale the MW
      // and LOWER the limit rather than the reverse — margin x volume is where
      // the money is, and Steve's own history is right calls at unpaid size.
      // Caps: half the most MW any auction ever awarded (you cannot buy what
      // is not sold, and past that size your own bid sets the price), and
      // ~$250 of likely outlay per ticket.
      maxMw: isMarket || isDiscovery ? (num(r.mw) || null) : null,
      suggestedMw: (() => {
        if (!isMarket && !isDiscovery) return Math.max(1, Math.min(50, Math.round(prevMw ?? 1)))
        const hours = AUCTION.hours[r.time_of_use] ?? 300
        const rate = cleared ?? ceiling ?? 0.1
        const byBudget = Math.floor(250 / Math.max(hours * rate, 1))
        const byLiquidity = Math.floor((num(r.mw) ?? 10) / 2)
        return Math.max(1, Math.min(byBudget, Math.max(byLiquidity, 1), 200))
      })(),
      holders: isDiscovery || isMarket ? (r.bids ?? null) : null,
      flag:
        tier === 'amber' && !hasHistory
          ? 'Never seen clearing an auction — the price cannot be verified as cheap.'
          : plainFlag(r.warnings) +
            (marginX !== null && marginX <= 1.05 && marginX > 1.0
              ? ' Margin over its usual cost is razor thin.'
              : ''),
      overbidNote: overbid
        ? `Your last bid ($${prevBid!.toFixed(2)}) was ABOVE this ceiling — cut it.`
        : r.hedge_type === 'OBL' && (isMarket || isDiscovery)
          ? 'Obligation: pays BOTH directions — a bad month can cost you, unlike your options.'
          : '',
    })
  }
  // Widest verified margin first: conviction order, not raw-edge order.
  ticket.sort((a, b) => (b.marginX ?? 0) - (a.marginX ?? 0) || b.ceiling - a.ceiling)
  red.sort((a, b) => (num(b.mw) ?? 0) - (num(a.mw) ?? 0))
  const hasBookRows = red.some(r => BOOK_HOLDER[r.book] !== undefined)

  return (
    <div className="space-y-5">
      <Panel
        title={AUCTION.name}
        subtitle={`bids open ${AUCTION.opens} · close ${AUCTION.closes} (${daysLeft >= 0 ? `${daysLeft} day${daysLeft === 1 ? '' : 's'} left` : 'CLOSED — the OCT sheet posts here once the valuation run completes, before bids open Sep 8'}) · delivery ${AUCTION.deliveryLabel}`}
      >
        {allRows.length === 0 ? (
          <Empty message="No valuations published." hint="The next valuation run posts them here." />
        ) : (
          <div className="space-y-1 text-[13px] text-zinc-400">
            <p className="max-w-[70ch]">
              One rule: <span className="font-semibold text-zinc-200">enter the green limit
              price as your bid — never more, never less</span>. The auction charges everyone
              the same clearing price (the price where supply meets demand), not what you bid,
              so bidding your full limit wins more paths at no extra cost. And every limit is
              already set below the path&apos;s valued payout: even if it clears at your full
              limit, history says you get back about $1.50 for every $1 paid.
            </p>
            <p className="text-[11px] text-zinc-600">
              valued on day-ahead prices to {allRows[0]?.window_end ?? ''} (trailing 2 months
              always held out) · September hour blocks: 336 weekday-peak (PeakWD) / 144
              weekend-peak (PeakWE) / 240 off-peak — Labor Day counts as a weekend
            </p>
          </div>
        )}
      </Panel>

      {ticket.length > 0 && <Ticket rows={ticket} auction={auction} />}

      {red.length > 0 && (
        <Panel
          title="Don't bid — and exactly why"
          subtitle="the auction has charged more than these paths returned"
        >
          <p className="mb-3 max-w-[70ch] text-[12.5px] text-zinc-500">
            Each row shows the price the auction has actually cleared at next to what the path
            has actually paid. Wherever clearing exceeds worth, the buyer funds the gap — and
            across 296 firms and 113M MWh, that gap averaged −$0.14/MWh.
            {hasBookRows && ' Some of these are among the largest positions in this account’s book; that is the point.'}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse">
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 text-right font-medium">Worth</th>
                  <th className="px-3 py-2 text-right font-medium">Usually clears</th>
                  <th className="px-3 py-2 text-right font-medium">You&apos;d overpay</th>
                  {hasBookRows && <th className="px-3 py-2 text-right font-medium">Was bid</th>}
                </tr>
              </thead>
              <tbody>
                {red.slice(0, 20).map((r) => {
                  const worth = num(r.value_mean)
                  const cleared = num(r.cleared_price)
                  const gap = worth !== null && cleared !== null ? cleared - worth : null
                  return (
                    <tr
                      key={`${r.source}-${r.sink}-${r.time_of_use}`}
                      className="border-b border-line/60 last:border-0"
                    >
                      <td className="px-3 py-2.5">
                        <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium text-zinc-300">
                          <span>{r.source}</span>
                          <span className="text-zinc-600">→</span>
                          <span>{r.sink}</span>
                        </div>
                        <div className="mt-0.5 text-[11px] text-zinc-600">
                          {r.time_of_use}
                          {BOOK_HOLDER[r.book] !== undefined && ` · ${num(r.mw)?.toFixed(0)} MW held`}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right tnum text-zinc-300">{usd(r.value_mean)}</td>
                      <td className="px-3 py-2.5 text-right tnum text-red-400">
                        {cleared !== null ? usd(r.cleared_price) : 'below 10¢ — too small to trade'}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum text-red-400">
                        {gap !== null && gap > 0 ? `${usd(gap)}/MWh` : '—'}
                      </td>
                      {hasBookRows && (
                        <td className="px-3 py-2.5 text-right tnum text-zinc-500">
                          {BOOK_HOLDER[r.book] !== undefined ? usd(r.bid_price) : '—'}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {red.length > 20 && (
            <p className="mt-2 text-[11px] text-zinc-600">largest 20 of {red.length} shown</p>
          )}
        </Panel>
      )}

      {(excluded.length > 0 || unpriced.length > 0) && (
        <Panel title="Not assessable" subtitle="excluded rather than guessed">
          <p className="text-[12.5px] text-zinc-500">
            {excluded.length > 0 &&
              `${excluded.length} path${excluded.length === 1 ? '' : 's'} reference a settlement point no longer active in ERCOT's registry. `}
            {unpriced.length > 0 &&
              `${unpriced.length} lack enough price history to value at all. `}
            Nothing here is scored — no data is treated as no opinion, not as approval.
          </p>
        </Panel>
      )}

      <Panel title="What these numbers are" subtitle="and what they are not">
        <div className="space-y-2.5 text-[13px] text-zinc-400">
          <p className="max-w-[70ch]">
            <span className="text-zinc-200">Worth</span> — what the path actually paid per MWh
            over the valuation window of day-ahead settlement. <span className="text-zinc-200">Bid
            price</span> — worth, trimmed where a driving constraint changed recently, history is
            thin, or the value rides on rare spikes. <span className="text-zinc-200">Likely
            outlay</span> — your MW × September hours × the price it usually clears at.{' '}
            <span className="text-zinc-200">Max outlay</span> — the same if it clears at your
            full bid, the worst case you authorise by submitting.
          </p>
          <p className="max-w-[70ch] border-l-2 border-red-500/60 pl-3 text-zinc-300">
            This is not a forecast. It stops overpaying and points at verified mispricing; it
            cannot promise September resembles the year behind it. Every prediction rule tested
            on this data failed out of sample — pricing discipline is what survived.
          </p>
        </div>
      </Panel>
    </div>
  )
}
