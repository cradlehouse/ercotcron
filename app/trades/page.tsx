// The three trades this data actually supports, each with its live scoreboard.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatCount, formatDateTime, formatUsd, num, styleFor } from '@/lib/prices'
import {
  query,
  type BatteryArbRow,
  type DartRow,
  type ExtremesRow,
} from '@/lib/supabase'

export const dynamic = 'force-dynamic'

function Explainer({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-b border-line px-4 py-2.5 text-[12px] leading-relaxed text-zinc-500">
      {children}
    </p>
  )
}

export default async function TradesPage() {
  const [dart, arb, extremes] = await Promise.all([
    query<DartRow>((db) =>
      db
        .from('dart_spread')
        .select('*')
        .order('interval_start', { ascending: false })
        .limit(400),
    ),
    query<BatteryArbRow>((db) =>
      db
        .from('daily_battery_arb')
        .select('*')
        .order('delivery_date', { ascending: false })
        .order('gross_per_mw', { ascending: false })
        .limit(60),
    ),
    query<ExtremesRow>((db) =>
      db
        .from('daily_extremes')
        .select('*')
        .order('delivery_date', { ascending: false })
        .limit(60),
    ),
  ])

  // Widest absolute spreads first — the hours a DART desk would have cared about.
  const dartRanked = [...dart.rows].sort(
    (a, b) => Math.abs(num(b.spread) ?? 0) - Math.abs(num(a.spread) ?? 0),
  )

  return (
    <div className="space-y-5">
      <Panel title="DART spread" subtitle="day-ahead vs real-time, widest hours first">
        <Explainer>
          The foundational ERCOT trade: commit at the day-ahead price, settle at
          real-time. A positive spread means real-time cleared above day-ahead —
          the hour rewarded buying DA; negative means day-ahead was the overpay.
          Desks trade this financially (virtuals/CRRs), generators trade it by
          choosing which market to sell into.
        </Explainer>
        {dart.error ? (
          <ErrorNote error={dart.error} />
        ) : dartRanked.length === 0 ? (
          <Empty
            message="No overlapping day-ahead and real-time hours yet."
            hint="This view needs the dam job to have run — trigger it or wait for the 12:45 CT tick."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">settlement point</th>
                  <th className="px-4 py-2 font-medium">hour</th>
                  <th className="px-4 py-2 text-right font-medium">day-ahead</th>
                  <th className="px-4 py-2 text-right font-medium">real-time avg</th>
                  <th className="px-4 py-2 text-right font-medium">spread</th>
                  <th className="px-4 py-2 text-right font-medium">winner</th>
                </tr>
              </thead>
              <tbody>
                {dartRanked.slice(0, 30).map((row) => {
                  const spread = num(row.spread) ?? 0
                  const partial = row.rt_intervals < 4
                  return (
                    <tr
                      key={`${row.settlement_point}-${row.interval_start}`}
                      className="border-b border-line/60 hover:bg-panel-2"
                    >
                      <td className="px-4 py-1.5 text-zinc-300">{row.settlement_point}</td>
                      <td className="tnum px-4 py-1.5 text-zinc-500">
                        {formatDateTime(row.interval_start)}
                        {partial && <span className="ml-1.5 text-amber-400/70">partial</span>}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatUsd(num(row.dam_price))}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatUsd(num(row.rt_avg))}
                      </td>
                      <td
                        className={`tnum px-4 py-1.5 text-right font-semibold ${
                          spread > 0 ? 'text-emerald-300' : spread < 0 ? 'text-red-400' : 'text-zinc-400'
                        }`}
                      >
                        {spread > 0 ? '+' : ''}
                        {formatUsd(spread)}
                      </td>
                      <td className="px-4 py-1.5 text-right text-zinc-500">
                        {spread > 0 ? 'bought DA' : spread < 0 ? 'sold DA' : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="px-4 py-2.5 text-[11px] text-zinc-600">
              “partial” marks hours where fewer than four 15-minute intervals have settled —
              the spread will move as the hour completes.
            </p>
          </div>
        )}
      </Panel>

      <Panel title="2-hour battery" subtitle="charge the two cheapest hours, discharge the two dearest">
        <Explainer>
          The standard storage benchmark. gross $/MW-day assumes perfect foresight
          and no losses — a real battery keeps roughly 85% after round-trip
          efficiency, and forecasting error takes another slice. The number is
          still the honest ceiling for what a day was worth to storage.
        </Explainer>
        {arb.error ? (
          <ErrorNote error={arb.error} />
        ) : arb.rows.length === 0 ? (
          <Empty message="No real-time hours accumulated yet." />
        ) : (
          <table className="w-full text-left">
            <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">settlement point</th>
                <th className="px-4 py-2 font-medium">day</th>
                <th className="px-4 py-2 text-right font-medium">charge avg</th>
                <th className="px-4 py-2 text-right font-medium">discharge avg</th>
                <th className="px-4 py-2 text-right font-medium">gross $/MW-day</th>
                <th className="px-4 py-2 text-right font-medium">hours seen</th>
              </tr>
            </thead>
            <tbody>
              {arb.rows.slice(0, 20).map((row) => (
                <tr
                  key={`${row.settlement_point}-${row.delivery_date}`}
                  className="border-b border-line/60 hover:bg-panel-2"
                >
                  <td className="px-4 py-1.5 text-zinc-300">{row.settlement_point}</td>
                  <td className="tnum px-4 py-1.5 text-zinc-500">{row.delivery_date}</td>
                  <td className="tnum px-4 py-1.5 text-right text-sky-300">
                    {formatUsd(num(row.charge_avg))}
                  </td>
                  <td className="tnum px-4 py-1.5 text-right text-amber-300">
                    {formatUsd(num(row.discharge_avg))}
                  </td>
                  <td className="tnum px-4 py-1.5 text-right font-semibold text-emerald-300">
                    {formatUsd(num(row.gross_per_mw))}
                  </td>
                  <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                    {row.hours_observed}
                    {row.hours_observed < 24 && (
                      <span className="ml-1 text-amber-400/70">partial day</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Daily extremes" subtitle="negative hours pay flexible load; $100+ hours pay peakers">
        <Explainer>
          Negative intervals are when wind and solar exceed load — generators pay
          to stay online, and anything that can shift consumption gets paid to
          take power. Scarcity intervals ($100+) are the hours batteries, peakers
          and demand response are built for.
        </Explainer>
        {extremes.error ? (
          <ErrorNote error={extremes.error} />
        ) : extremes.rows.length === 0 ? (
          <Empty message="No real-time data accumulated yet." />
        ) : (
          <table className="w-full text-left">
            <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">settlement point</th>
                <th className="px-4 py-2 font-medium">day</th>
                <th className="px-4 py-2 text-right font-medium">negative 15-min</th>
                <th className="px-4 py-2 text-right font-medium">$100+ 15-min</th>
                <th className="px-4 py-2 text-right font-medium">low</th>
                <th className="px-4 py-2 text-right font-medium">high</th>
                <th className="px-4 py-2 text-right font-medium">avg</th>
              </tr>
            </thead>
            <tbody>
              {extremes.rows.slice(0, 20).map((row) => (
                <tr
                  key={`${row.settlement_point}-${row.delivery_date}`}
                  className="border-b border-line/60 hover:bg-panel-2"
                >
                  <td className="px-4 py-1.5 text-zinc-300">{row.settlement_point}</td>
                  <td className="tnum px-4 py-1.5 text-zinc-500">{row.delivery_date}</td>
                  <td
                    className={`tnum px-4 py-1.5 text-right ${
                      row.negative_intervals ? 'text-sky-300' : 'text-zinc-600'
                    }`}
                  >
                    {formatCount(row.negative_intervals)}
                  </td>
                  <td
                    className={`tnum px-4 py-1.5 text-right ${
                      row.scarcity_intervals ? 'text-red-400' : 'text-zinc-600'
                    }`}
                  >
                    {formatCount(row.scarcity_intervals)}
                  </td>
                  <td className={`tnum px-4 py-1.5 text-right ${styleFor(num(row.min_price)).text}`}>
                    {formatUsd(num(row.min_price))}
                  </td>
                  <td className={`tnum px-4 py-1.5 text-right ${styleFor(num(row.max_price)).text}`}>
                    {formatUsd(num(row.max_price))}
                  </td>
                  <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                    {formatUsd(num(row.avg_price))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}
