// The auction order ticket — what to bid, at what price, how many MW, by when.
//
// Redesigned after a cold read as the trader it serves. The failures it fixes:
// the rejection table hid its own reasoning (no clearing-price column), paths
// with NO auction history were green-lit as if absence of evidence were
// approval, the thinnest margin led the buy list, a nickel ceiling made the
// tool look innumerate, and nothing said which auction any of this was for.
//
// Tiers now mean something operational:
//   green  = worth more than the auction has actually charged, on real
//            clearing history, no cautions — bid the shown price
//   amber  = positive value but unverifiable (never seen clearing) or
//            flagged — size small if at all
//   red    = the auction charges more than the path has returned, with the
//            clearing price SHOWN so the rejection argues for itself

import { Empty, ErrorNote, Panel } from '@/app/components'
import { num } from '@/lib/prices'
import { query, type PathValuation, type SettlementPoint } from '@/lib/supabase'
import { Ticket, type AuctionMeta, type TicketRow } from './ticket'

export const dynamic = 'force-dynamic'

// From ERCOT's CRR Activity Calendar (WMS-approved edition on file). September
// 2026 TOU hours are computed, not assumed: Labor Day (7 Sep) is a NERC
// holiday, so its peak hours count as PeakWE — 21 weekdays x16, 9 weekend-rule
// days x16, remainder off-peak. Fixed constants drift a few percent by month,
// which is exactly the error the trader's own workbook carries.
const AUCTION: Omit<AuctionMeta, 'daysLeft'> = {
  name: '2026.SEP.Monthly.Auction',
  opens: '2026-08-11',
  closes: '2026-08-13',
  deliveryStart: '9/1/2026',
  deliveryEnd: '9/30/2026',
  deliveryLabel: '1–30 Sep 2026',
  hours: { PeakWD: 336, PeakWE: 144, 'Off-peak': 240 },
  holder: 'XSAAIC',
}

const MATERIALITY = 0.1 // ceilings below 10c are noise, not trades

function plainFlag(w: string | null): string {
  if (!w) return ''
  if (w.includes('fading')) return 'Congestion fading — recent months are far below the average this price is built on.' ''
  if (w.includes('spike')) return 'Pays rarely but big — expect long waits between payoffs.'
  if (w.includes('re-rated')) return `Grid changed near this path in the last 90 days (${w.split(':')[0]}) — history is less reliable.`
  if (w.includes('silent')) return `A driving constraint has gone quiet (${w.split(':')[0]}) — the congestion may be gone.`
  return w
}

function usd(v: number | string | null | undefined): string {
  const n = num(v)
  return n === null ? '—' : `$${n.toFixed(2)}`
}

export default async function BidsPage() {
  const [{ rows: allRows, error }, { rows: points }] = await Promise.all([
    query<PathValuation>((db) => db.from('path_valuations').select('*')),
    query<SettlementPoint>((db) => db.from('settlement_points').select('name,active')),
  ])
  const active = new Set(points.filter((p) => p.active).map((p) => p.name))
  const daysLeft = Math.ceil(
    (new Date(`${AUCTION.closes}T17:00:00-05:00`).getTime() - Date.now()) / 86_400_000,
  )
  const auction: AuctionMeta = { ...AUCTION, daysLeft }

  const ticket: TicketRow[] = []
  const red: PathValuation[] = []
  const excluded: PathValuation[] = []
  const unpriced: PathValuation[] = []

  for (const r of allRows) {
    const ceiling = num(r.ceiling)
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
    const tier: TicketRow['tier'] =
      hasHistory && !flagged && marginX !== null && marginX > 1.05 ? 'green' : 'amber'
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
      ceiling,
      worth,
      cleared,
      marginX,
      pctHours: num(r.pct_hours_pos),
      prevBid: isDiscovery || isMarket ? null : prevBid,
      prevMw: isDiscovery || isMarket ? null : prevMw,
      suggestedMw: isMarket ? 5 : isDiscovery ? 10 : Math.max(1, Math.min(50, Math.round(prevMw ?? 1))),
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

  return (
    <div className="space-y-5">
      <Panel
        title={AUCTION.name}
        subtitle={`bids open ${AUCTION.opens} · close ${AUCTION.closes} (${daysLeft >= 0 ? `${daysLeft} day${daysLeft === 1 ? '' : 's'} left` : 'CLOSED'}) · delivery ${AUCTION.deliveryLabel}`}
      >
        {error ? (
          <ErrorNote error={error} />
        ) : allRows.length === 0 ? (
          <Empty message="No valuations published." hint="Run strategy/valuation_screen.py first." />
        ) : (
          <div className="space-y-1 text-[13px] text-zinc-400">
            <p className="max-w-[70ch]">
              One rule: <span className="font-semibold text-zinc-200">enter the shown price as
              your bid and never more</span>. The auction charges the clearing price, not your
              bid — bidding the full ceiling wins more paths at no extra cost. Bidding a timid
              fraction of it only loses auctions you should have won.
            </p>
            <p className="text-[11px] text-zinc-600">
              valued on 12 months of day-ahead prices to {allRows[0]?.window_end ?? ''} (trailing
              2 months always held out) · September hours used: 336 PeakWD / 144 PeakWE / 240
              Off-peak — Labor Day counts as weekend
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
            across 296 firms and 113M MWh, that gap averaged −$0.14/MWh. Some of these are this
            book&apos;s biggest positions; that is the point.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse">
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 text-right font-medium">Worth</th>
                  <th className="px-3 py-2 text-right font-medium">Usually clears</th>
                  <th className="px-3 py-2 text-right font-medium">You&apos;d overpay</th>
                  <th className="px-3 py-2 text-right font-medium">Was bid</th>
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
                          {r.time_of_use} · {num(r.mw)?.toFixed(0)} MW held
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right tnum text-zinc-300">{usd(r.value_mean)}</td>
                      <td className="px-3 py-2.5 text-right tnum text-red-400">
                        {cleared !== null ? usd(r.cleared_price) : 'below 10¢ — too small to trade'}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum text-red-400">
                        {gap !== null && gap > 0 ? `${usd(gap)}/MWh` : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right tnum text-zinc-500">{usd(r.bid_price)}</td>
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
            over twelve months of day-ahead settlement. <span className="text-zinc-200">Bid
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
