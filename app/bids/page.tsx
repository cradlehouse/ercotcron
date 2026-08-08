// What to bid, at what price, and why — the decision screen before an auction.
//
// CRR auctions clear at a uniform price: your bid decides whether you win, not
// what you pay. So the only mistake is bidding above what a path is worth, and
// the only number that matters is the ceiling. Everything here exists to
// justify or qualify that one figure.
//
// Live by construction — this reads path_valuations on each request, so it
// tracks whatever the last valuation run wrote rather than a snapshot.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { num } from '@/lib/prices'
import { query, type PathValuation } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

function usd(v: number | string | null | undefined, dp = 2): string {
  const n = num(v)
  return n === null ? '—' : `$${n.toFixed(dp)}`
}

/** Ceiling over usual clearing price: how much room before the trade is marginal. */
function Margin({ ceiling, clears }: { ceiling: number | null; clears: number | null }) {
  if (ceiling === null || clears === null || clears <= 0) {
    return <span className="text-[11px] italic text-zinc-600">no auction history</span>
  }
  const ratio = ceiling / clears
  const width = Math.max(4, Math.min(100, (ratio / 2) * 100))
  const tone = ratio >= 1.5 ? 'bg-emerald-400' : ratio >= 1.05 ? 'bg-amber-400' : 'bg-red-400'
  return (
    <div className="min-w-[130px]">
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-zinc-600 tnum">{ratio.toFixed(2)}× its usual cost</div>
    </div>
  )
}

function Path({ row }: { row: PathValuation }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium text-zinc-200">
        <span>{row.source}</span>
        <span className="text-amber-500">→</span>
        <span>{row.sink}</span>
      </div>
      <div className="mt-0.5 text-[11px] text-zinc-600">
        {row.time_of_use} · {row.hedge_type} · {num(row.mw)?.toFixed(0) ?? '—'} MW
      </div>
    </div>
  )
}

export default async function BidsPage() {
  const { rows, error } = await query<PathValuation>((db) =>
    db.from('path_valuations').select('*').order('edge', { ascending: false }),
  )

  // A path is worth bidding when its ceiling clears what the auction usually
  // charges. Everything else is the market pricing it above its own history.
  const priced = rows.filter((r) => num(r.value_mean) !== null)
  const bid = priced.filter((r) => {
    const c = num(r.value_mean)
    const cl = num(r.bid_price)
    return c !== null && (cl === null || c > cl)
  })
  const skip = priced.filter((r) => !bid.includes(r))
  const unpriced = rows.filter((r) => num(r.value_mean) === null)
  const book = rows[0]?.book ?? null
  const computed = rows[0]?.computed_at ?? null

  return (
    <div className="space-y-5">
      <Panel
        title="Bid ceilings"
        subtitle={
          book
            ? `${book} — valued ${rows[0]?.window_start ?? ''} to ${rows[0]?.window_end ?? ''}`
            : 'no valuation has been published yet'
        }
      >
        {error ? (
          <ErrorNote error={error} />
        ) : rows.length === 0 ? (
          <Empty
            message="No valuations published."
            hint="Run strategy/valuation_screen.py against a bid book to populate this."
          />
        ) : (
          <div className="space-y-1 text-[13px] text-zinc-400">
            <p className="max-w-[68ch]">
              Bid up to the green figure and no further. CRR auctions clear at a uniform price, so
              bidding above the clearing price costs nothing — you pay what the auction clears at,
              not what you bid. The only mistake is bidding past what the path is worth.
            </p>
            <p className="text-[11px] text-zinc-600">
              {bid.length} worth bidding · {skip.length} priced above their value ·{' '}
              {unpriced.length} without enough history to value
              {computed ? ` · computed ${new Date(computed).toLocaleString('en-GB')}` : ''}
            </p>
          </div>
        )}
      </Panel>

      {bid.length > 0 && (
        <Panel title="Bid these" subtitle="ceiling clears what the auction usually charges">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 text-right font-medium">Bid up to</th>
                  <th className="px-3 py-2 text-right font-medium">Was bid</th>
                  <th className="px-3 py-2 text-right font-medium">Worth</th>
                  <th className="px-3 py-2 text-right font-medium">Typical hour</th>
                  <th className="px-3 py-2 text-right font-medium">% hrs paid</th>
                  <th className="px-3 py-2 font-medium">Margin</th>
                  <th className="px-3 py-2 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {bid.map((r) => (
                  <tr
                    key={`${r.source}-${r.sink}-${r.time_of_use}-${r.hedge_type}`}
                    className="border-b border-line/60 last:border-0 hover:bg-zinc-900/40"
                  >
                    <td className="px-3 py-2.5"><Path row={r} /></td>
                    <td className="px-3 py-2.5 text-right tnum text-[15px] font-semibold text-emerald-300">
                      {usd(r.value_mean)}
                    </td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-500">{usd(r.bid_price)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-300">{usd(r.value_mean)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-400">{usd(r.value_median)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-400">
                      {num(r.pct_hours_pos)?.toFixed(0) ?? '—'}%
                    </td>
                    <td className="px-3 py-2.5">
                      <Margin ceiling={num(r.value_mean)} clears={num(r.bid_price)} />
                    </td>
                    <td className="px-3 py-2.5 text-[11px] text-zinc-500">
                      {r.warnings ? (
                        <span className="text-amber-400/90">{r.warnings}</span>
                      ) : (
                        'full history, no flags'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {skip.length > 0 && (
        <Panel
          title="Don't bid"
          subtitle="the auction charges more than these have returned"
        >
          <p className="mb-3 max-w-[68ch] text-[12.5px] text-zinc-500">
            Overpaying is the normal state of this auction rather than the exception: across 296
            firms and 113 million MWh, CRR buyers paid $0.858 and collected $0.718. These are the
            paths where that gap shows up in this book.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 text-right font-medium">Worth</th>
                  <th className="px-3 py-2 text-right font-medium">Was bid</th>
                  <th className="px-3 py-2 text-right font-medium">Worst 5% hr</th>
                  <th className="px-3 py-2 font-medium">Driving constraints</th>
                </tr>
              </thead>
              <tbody>
                {skip.slice(0, 25).map((r) => (
                  <tr
                    key={`${r.source}-${r.sink}-${r.time_of_use}-${r.hedge_type}`}
                    className="border-b border-line/60 last:border-0 hover:bg-zinc-900/40"
                  >
                    <td className="px-3 py-2.5"><Path row={r} /></td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-300">{usd(r.value_mean)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-red-400">{usd(r.bid_price)}</td>
                    <td className="px-3 py-2.5 text-right tnum text-zinc-500">{usd(r.value_p05)}</td>
                    <td className="px-3 py-2.5 text-[11px] text-zinc-500">{r.drivers ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {skip.length > 25 && (
            <p className="mt-2 text-[11px] text-zinc-600">
              showing the 25 largest of {skip.length}
            </p>
          )}
        </Panel>
      )}

      <Panel title="How to read this" subtitle="what the numbers are, and what they are not">
        <div className="space-y-3 text-[13px] text-zinc-400">
          <p className="max-w-[70ch]">
            <span className="text-zinc-200">Worth</span> is what the path actually paid per MWh
            over the valuation window, from ERCOT day-ahead settlement prices. An option pays
            max(0, sink − source); an obligation pays the signed difference. The trailing two
            months are always held back.
          </p>
          <p className="max-w-[70ch]">
            <span className="text-zinc-200">Typical hour</span> is the median. When it sits far
            below Worth, the average is carried by rare spikes — those pay eventually, but the
            waiting between payoffs is hard on a small book.
          </p>
          <p className="max-w-[70ch]">
            <span className="text-zinc-200">Confidence</span> flags a driving constraint that was
            re-rated in the last 90 days or has gone quiet. Either means the history may be
            describing a network that no longer exists.
          </p>
          <p className="max-w-[70ch] border-l-2 border-red-500/60 pl-3 text-zinc-300">
            This is not a forecast. It says what a path has been worth and how far that estimate
            can be trusted — it stops overpaying, it cannot promise a profit. Every predictive rule
            tested against this data failed out of sample; valuation and risk-flagging are what
            survived.
          </p>
        </div>
      </Panel>
    </div>
  )
}
