// Why prices did what they did, and where that is repeatable enough to trade.
//
// Every panel here reports its own sample size and its own noise, because the
// failure mode is not a wrong number — it is a confident number computed from
// too little data. Rankings are by reliability, never by size.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatCount, formatUsd, num } from '@/lib/prices'
import {
  query,
  type CrrEdgeRow,
  type PriceStackRow,
  type WindSensitivityRow,
} from '@/lib/supabase'

export const dynamic = 'force-dynamic'

/** Horizontal bar for a 0..max value, drawn with a div rather than a chart. */
function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const pct = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0
  return (
    <span className="inline-block h-1.5 w-24 rounded-sm bg-panel-2 align-middle">
      <span className={`block h-full rounded-sm ${tone}`} style={{ width: `${pct}%` }} />
    </span>
  )
}

export default async function WhyPage() {
  const [stack, wind, edge] = await Promise.all([
    query<PriceStackRow>((db) => db.from('price_stack').select('*').order('bucket')),
    query<WindSensitivityRow>((db) =>
      db.from('wind_sensitivity').select('*').order('hour_ending'),
    ),
    query<CrrEdgeRow>((db) =>
      db.from('crr_edge').select('*').order('t_stat', { ascending: false }).limit(200),
    ),
  ])

  const maxScarcity = Math.max(1, ...stack.rows.map((r) => num(r.pct_scarcity) ?? 0))
  const maxSlope = Math.max(
    0.0001,
    ...wind.rows.map((r) => Math.abs(num(r.price_per_mw_wind) ?? 0)),
  )

  // Both tails: the auction can be wrong in either direction, and a path that
  // reliably overprices is as tradeable as one that underprices — you sell it.
  const ranked = [...edge.rows].sort(
    (a, b) => Math.abs(num(b.t_stat) ?? 0) - Math.abs(num(a.t_stat) ?? 0),
  )

  return (
    <div className="space-y-5">
      <Panel title="The supply stack" subtitle="day-ahead price against net load (demand − wind − solar)">
        <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
          Price is set by the marginal generator, and net load decides which one
          that is. The number worth reading is not the median but the gap between
          median and p95 — where they separate is where scarcity begins, and that
          break point is the single most useful figure for predicting a spike.
        </p>
        {stack.error ? (
          <ErrorNote error={stack.error} />
        ) : stack.rows.length === 0 ? (
          <Empty
            message="Needs wind, solar and load history."
            hint="Backfill wind, solar and load — the live jobs only hold an 8-day window."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">net load (MW)</th>
                  <th className="px-4 py-2 text-right font-medium">median</th>
                  <th className="px-4 py-2 text-right font-medium">p95</th>
                  <th className="px-4 py-2 text-right font-medium">spread</th>
                  <th className="px-4 py-2 text-right font-medium">$100+ hours</th>
                  <th className="px-4 py-2 text-right font-medium">negative</th>
                  <th className="px-4 py-2 text-right font-medium">hours</th>
                </tr>
              </thead>
              <tbody>
                {stack.rows.map((row) => {
                  const med = num(row.median_price)
                  const p95 = num(row.p95_price)
                  const gap = med !== null && p95 !== null ? p95 - med : null
                  const scarcity = num(row.pct_scarcity) ?? 0
                  return (
                    <tr key={row.bucket} className="border-b border-line/60 hover:bg-panel-2">
                      <td className="tnum px-4 py-1.5 text-zinc-400">
                        {formatCount(row.net_load_from)}–{formatCount(row.net_load_to)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-300">
                        {formatUsd(med)}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right ${
                          (p95 ?? 0) >= 100 ? 'text-red-400 font-semibold' : 'text-zinc-400'
                        }`}
                      >
                        {formatUsd(p95)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                        {formatUsd(gap)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right">
                        <span className="mr-2 text-zinc-400">{scarcity.toFixed(1)}%</span>
                        <Bar value={scarcity} max={maxScarcity} tone="bg-red-400" />
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-sky-300">
                        {num(row.pct_negative)?.toFixed(1) ?? '—'}%
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

      <Panel title="Wind sensitivity by hour" subtitle="$/MWh of price movement per MW of wind">
        <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
          Normally negative: more wind, cheaper power. r² says how much of the
          price that actually explains — a steep slope with a trivial r² is a
          coincidence, so read them together and neither alone.
        </p>
        {wind.error ? (
          <ErrorNote error={wind.error} />
        ) : wind.rows.length === 0 ? (
          <Empty message="Needs wind history against day-ahead prices." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">hour ending</th>
                  <th className="px-4 py-2 text-right font-medium">$/MW of wind</th>
                  <th className="px-4 py-2 text-right font-medium">strength</th>
                  <th className="px-4 py-2 text-right font-medium">r²</th>
                  <th className="px-4 py-2 text-right font-medium">avg wind</th>
                  <th className="px-4 py-2 text-right font-medium">avg price</th>
                  <th className="px-4 py-2 text-right font-medium">hours</th>
                </tr>
              </thead>
              <tbody>
                {wind.rows.map((row) => {
                  const slope = num(row.price_per_mw_wind)
                  const r2 = num(row.r2) ?? 0
                  return (
                    <tr key={row.hour_ending} className="border-b border-line/60 hover:bg-panel-2">
                      <td className="tnum px-4 py-1.5 text-zinc-400">
                        HE {String(row.hour_ending).padStart(2, '0')}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right ${
                          (slope ?? 0) < 0 ? 'text-sky-300' : 'text-amber-300'
                        }`}
                      >
                        {slope === null ? '—' : slope.toFixed(5)}
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        <Bar value={slope ?? 0} max={maxSlope} tone="bg-sky-400" />
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right ${
                          r2 >= 0.3 ? 'text-emerald-300' : r2 >= 0.1 ? 'text-amber-300' : 'text-zinc-600'
                        }`}
                      >
                        {r2.toFixed(3)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                        {formatCount(row.avg_wind_mw)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatUsd(num(row.avg_price))}
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

      <Panel
        title="CRR edge"
        subtitle="what the auction charged against what the path paid, ranked by reliability"
      >
        <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
          Sorted by t-statistic, not by size. A $2 edge with $8 of noise across a
          year is nothing; a $2 edge with $0.80 is a signal. Ranking by average
          edge would put the loudest paths on top rather than the most repeatable,
          which is exactly how a backtest talks you into a strategy. Treat |t|
          under 2 as unproven whatever the edge column says.
        </p>
        {edge.error ? (
          <ErrorNote error={edge.error} />
        ) : ranked.length === 0 ? (
          <Empty
            message="No paths with enough auctions yet."
            hint="Needs at least 4 auctions where both source and sink are priced."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">path</th>
                  <th className="px-4 py-2 font-medium">block</th>
                  <th className="px-4 py-2 font-medium">type</th>
                  <th className="px-4 py-2 text-right font-medium">paid</th>
                  <th className="px-4 py-2 text-right font-medium">received</th>
                  <th className="px-4 py-2 text-right font-medium">edge</th>
                  <th className="px-4 py-2 text-right font-medium">noise</th>
                  <th className="px-4 py-2 text-right font-medium">t</th>
                  <th className="px-4 py-2 text-right font-medium">won</th>
                  <th className="px-4 py-2 text-right font-medium">auctions</th>
                </tr>
              </thead>
              <tbody>
                {ranked.slice(0, 40).map((row) => {
                  const t = num(row.t_stat)
                  const edgeV = num(row.avg_edge_per_mwh)
                  const strong = Math.abs(t ?? 0) >= 2
                  return (
                    <tr
                      key={`${row.source}-${row.sink}-${row.time_of_use}-${row.hedge_type}`}
                      className="border-b border-line/60 hover:bg-panel-2"
                    >
                      <td className="px-4 py-1.5 text-zinc-300">
                        {row.source.replace(/^(LZ|HB)_/, '')} → {row.sink.replace(/^(LZ|HB)_/, '')}
                      </td>
                      <td className="px-4 py-1.5 text-zinc-500">{row.time_of_use}</td>
                      <td className="px-4 py-1.5 text-zinc-600">{row.hedge_type}</td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatUsd(num(row.avg_cost_per_mwh), 3)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatUsd(num(row.avg_payoff_per_mwh), 3)}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right font-semibold ${
                          (edgeV ?? 0) > 0 ? 'text-emerald-300' : 'text-red-400'
                        }`}
                      >
                        {(edgeV ?? 0) > 0 ? '+' : ''}
                        {formatUsd(edgeV, 3)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                        {formatUsd(num(row.edge_sd), 3)}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right font-semibold ${
                          strong ? 'text-emerald-300' : 'text-zinc-600'
                        }`}
                      >
                        {t === null ? '—' : t.toFixed(2)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                        {num(row.pct_profitable)?.toFixed(0) ?? '—'}%
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                        {row.auctions}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="px-4 py-2.5 text-[11px] text-zinc-600">
              Coverage is partial: only paths whose source and sink are both
              priced here appear, which is the liquid hub-and-zone subset rather
              than every auction path.
            </p>
          </div>
        )}
      </Panel>
    </div>
  )
}
