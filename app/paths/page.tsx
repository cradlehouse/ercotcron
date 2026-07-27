// Path spreads — the payoff side of a congestion revenue right.
//
// A PTP Obligation pays the congestion difference between a source and a sink,
// and the day-ahead price difference between two settlement points is that
// difference. So this ranks which paths paid, from data already stored.
//
// It cannot rank which were *profitable*: what a CRR cost at auction lives in
// ERCOT's CRR/MIS system, not the public reports API. The page says so rather
// than letting a big average read as a big return.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatCount, formatUsd, num } from '@/lib/prices'
import { query, type PathDartRow, type PathSpreadRow } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

function label(a: string, b: string): string {
  return `${a.replace(/^(LZ|HB)_/, '')} → ${b.replace(/^(LZ|HB)_/, '')}`
}

/** Signed money, coloured by direction. */
function Spread({ value, bold = false }: { value: number | null; bold?: boolean }) {
  const tone = value === null ? 'text-zinc-600' : value > 0 ? 'text-emerald-300' : value < 0 ? 'text-red-400' : 'text-zinc-400'
  return (
    <span className={`tnum ${tone} ${bold ? 'font-semibold' : ''}`}>
      {value !== null && value > 0 ? '+' : ''}
      {formatUsd(value)}
    </span>
  )
}

export default async function PathsPage() {
  const [spread, dart] = await Promise.all([
    query<PathSpreadRow>((db) =>
      db.from('path_spread').select('*').order('avg_abs_spread', { ascending: false }).limit(60),
    ),
    query<PathDartRow>((db) =>
      db.from('path_spread_dart').select('*').limit(200),
    ),
  ])

  // Widest day-ahead-vs-real-time miss first: the paths where day-ahead
  // congestion pricing was furthest from what actually happened.
  const missRanked = [...dart.rows].sort(
    (a, b) => Math.abs(num(b.avg_miss) ?? 0) - Math.abs(num(a.avg_miss) ?? 0),
  )

  return (
    <div className="space-y-5">
      <Panel title="Path spreads" subtitle="day-ahead congestion between settlement points, last 90 days">
        <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
          A congestion revenue right pays the price difference between a source and
          a sink, so these are the paths that paid. They are <em>not</em> ranked by
          profit — what a CRR cost at auction is published in ERCOT&apos;s CRR system,
          not this API, so the purchase price is missing from every row below.
          A path with a wide average spread may still have been expensive enough
          at auction to lose money.
        </p>
        {spread.error ? (
          <ErrorNote error={spread.error} />
        ) : spread.rows.length === 0 ? (
          <Empty
            message="No overlapping day-ahead hours yet."
            hint="Needs dam_spp history across at least two settlement points."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">path</th>
                  <th className="px-4 py-2 text-right font-medium">avg spread</th>
                  <th className="px-4 py-2 text-right font-medium">avg |spread|</th>
                  <th className="px-4 py-2 text-right font-medium">volatility</th>
                  <th className="px-4 py-2 text-right font-medium">b higher</th>
                  <th className="px-4 py-2 text-right font-medium">max</th>
                  <th className="px-4 py-2 text-right font-medium">min</th>
                  <th className="px-4 py-2 text-right font-medium">hours</th>
                </tr>
              </thead>
              <tbody>
                {spread.rows.map((row) => (
                  <tr
                    key={`${row.point_a}-${row.point_b}`}
                    className="border-b border-line/60 hover:bg-panel-2"
                  >
                    <td className="px-4 py-1.5 text-zinc-300">{label(row.point_a, row.point_b)}</td>
                    <td className="px-4 py-1.5 text-right">
                      <Spread value={num(row.avg_spread)} bold />
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-300">
                      {formatUsd(num(row.avg_abs_spread))}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                      {formatUsd(num(row.spread_sd))}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                      {num(row.pct_b_higher)?.toFixed(0) ?? '—'}%
                    </td>
                    <td className="px-4 py-1.5 text-right">
                      <Spread value={num(row.max_spread)} />
                    </td>
                    <td className="px-4 py-1.5 text-right">
                      <Spread value={num(row.min_spread)} />
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                      {formatCount(row.hours)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="px-4 py-2.5 text-[11px] text-zinc-600">
              Each path appears once, ordered a → b. The reverse direction is the
              same number negated.
            </p>
          </div>
        )}
      </Panel>

      <Panel
        title="Where day-ahead mispriced congestion"
        subtitle="realised real-time spread minus the day-ahead spread, widest miss first"
      >
        <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
          A CRR settles against day-ahead. When the real-time spread persistently
          exceeds the day-ahead spread on a path, day-ahead was underpricing that
          congestion — and consistency matters more than size, which is what the
          volatility column is for. A large average miss with larger volatility is
          noise, not an edge.
        </p>
        {dart.error ? (
          <ErrorNote error={dart.error} />
        ) : missRanked.length === 0 ? (
          <Empty
            message="No paths with both day-ahead and real-time coverage yet."
            hint="Needs overlapping dam_spp and rt_spp history on the same hours."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">path</th>
                  <th className="px-4 py-2 text-right font-medium">day-ahead</th>
                  <th className="px-4 py-2 text-right font-medium">real-time</th>
                  <th className="px-4 py-2 text-right font-medium">miss</th>
                  <th className="px-4 py-2 text-right font-medium">miss volatility</th>
                  <th className="px-4 py-2 text-right font-medium">signal</th>
                  <th className="px-4 py-2 text-right font-medium">hours</th>
                </tr>
              </thead>
              <tbody>
                {missRanked.slice(0, 30).map((row) => {
                  const miss = num(row.avg_miss)
                  const sd = num(row.miss_sd)
                  // Mean over standard deviation: how much of the miss survives
                  // its own noise. Below ~0.2 there is nothing to trade.
                  const ratio = miss !== null && sd ? Math.abs(miss) / sd : null
                  return (
                    <tr
                      key={`${row.point_a}-${row.point_b}`}
                      className="border-b border-line/60 hover:bg-panel-2"
                    >
                      <td className="px-4 py-1.5 text-zinc-300">
                        {label(row.point_a, row.point_b)}
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <Spread value={num(row.avg_dam_spread)} />
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <Spread value={num(row.avg_rt_spread)} />
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <Spread value={miss} bold />
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                        {formatUsd(sd)}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right ${
                          (ratio ?? 0) >= 0.5
                            ? 'text-emerald-300'
                            : (ratio ?? 0) >= 0.2
                              ? 'text-amber-300'
                              : 'text-zinc-600'
                        }`}
                      >
                        {ratio === null ? '—' : ratio.toFixed(2)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                        {formatCount(row.hours)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
