// The opportunity scanner: z-scored spreads, persistence, tails, and what the
// auction charges for uncertainty. One screen, four instruments, all with a
// time axis or a distribution — never a snapshot pretending to be a signal.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatCount, formatDateTime, formatUsd, num } from '@/lib/prices'
import {
  query,
  type DurationRow,
  type ImpliedVolRow,
  type NodeHourRow,
  type SpreadZRow,
} from '@/lib/supabase'

export const dynamic = 'force-dynamic'

// The scanner reads the tracked hubs and zones. The z-score view computes
// trailing windows over the full nodal map, which is a reporting query, not a
// page load — and until the all-points real-time backfill lands, nodal rows
// are patchy anyway.
const POINTS = [
  'HB_BUSAVG', 'HB_HUBAVG', 'HB_HOUSTON', 'HB_NORTH', 'HB_SOUTH', 'HB_WEST', 'HB_PAN',
  'LZ_AEN', 'LZ_CPS', 'LZ_HOUSTON', 'LZ_LCRA', 'LZ_NORTH', 'LZ_RAYBN', 'LZ_SOUTH', 'LZ_WEST',
]
const IN = `(${POINTS.join(',')})`

function zTone(z: number | null): string {
  if (z === null) return 'bg-zinc-800'
  if (z >= 2) return 'bg-red-500'
  if (z >= 1) return 'bg-amber-500'
  if (z <= -2) return 'bg-sky-500'
  if (z <= -1) return 'bg-sky-700'
  return 'bg-emerald-900'
}

function tTone(t: number | null): string {
  if (t === null) return 'text-zinc-600'
  const a = Math.abs(t)
  if (a >= 4) return t > 0 ? 'text-red-400 font-semibold' : 'text-sky-300 font-semibold'
  if (a >= 2) return t > 0 ? 'text-amber-300' : 'text-sky-400'
  return 'text-zinc-600'
}

export default async function ScannerPage() {
  const [zraw, nodeHour, duration, vol] = await Promise.all([
    query<SpreadZRow>((db) =>
      db
        .from('spread_zscore')
        .select('settlement_point,interval_start,hour_ending,dam_price,rt_price,spread,z')
        .in('settlement_point', POINTS)
        .gte('interval_start', new Date(Date.now() - 48 * 3600_000).toISOString())
        .order('interval_start', { ascending: true })
        .limit(3000),
    ),
    query<NodeHourRow>((db) =>
      db.from('node_hour_spread').select('*').in('settlement_point', POINTS),
    ),
    query<DurationRow>((db) =>
      db.from('spread_duration').select('*').in('settlement_point', POINTS),
    ),
    query<ImpliedVolRow>((db) =>
      db
        .from('crr_implied_vol_summary')
        .select('*')
        .gte('total_mw', 500)
        .order('avg_premium', { ascending: false })
        .limit(20),
    ),
  ])

  // strip: per point, the last 48 hourly z cells in time order
  const byPoint = new Map<string, SpreadZRow[]>()
  for (const row of zraw.rows) {
    const list = byPoint.get(row.settlement_point) ?? []
    list.push(row)
    byPoint.set(row.settlement_point, list)
  }
  const strip = POINTS.map((p) => {
    const rows = byPoint.get(p) ?? []
    const latest = rows[rows.length - 1]
    return { point: p, rows, latest }
  }).sort((a, b) => Math.abs(num(b.latest?.z) ?? 0) - Math.abs(num(a.latest?.z) ?? 0))

  const grid = new Map<string, NodeHourRow>()
  for (const row of nodeHour.rows) grid.set(`${row.settlement_point}-${row.hour_ending}`, row)

  return (
    <div className="space-y-5">
      <Panel
        title="Spread scanner"
        subtitle="DA−RT spread z-scored against each point's own trailing week · last 48h · biggest live |z| first"
      >
        {zraw.error ? (
          <ErrorNote error={zraw.error} />
        ) : strip.every((s) => s.rows.length === 0) ? (
          <Empty message="No scored hours yet — needs overlapping day-ahead and real-time data." />
        ) : (
          <div className="space-y-1 p-3">
            <div className="mb-2 flex gap-4 text-[11px] text-zinc-600">
              <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-red-500" />DA ≫ RT (z ≥ 2)</span>
              <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-500" />z ≥ 1</span>
              <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-emerald-900" />normal</span>
              <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-sky-500" />RT ≫ DA (z ≤ −2)</span>
            </div>
            {strip.map(({ point, rows, latest }) => (
              <div key={point} className="flex items-center gap-2">
                <span className="w-24 shrink-0 text-[11px] text-zinc-400">{point}</span>
                <span className="flex h-4 flex-1 gap-px overflow-hidden rounded-sm">
                  {rows.map((r) => (
                    <span
                      key={r.interval_start}
                      title={`${formatDateTime(r.interval_start)} · spread ${formatUsd(num(r.spread))} · z ${num(r.z)?.toFixed(1) ?? '—'}`}
                      className={`h-full flex-1 ${zTone(num(r.z))}`}
                    />
                  ))}
                </span>
                <span className={`tnum w-14 shrink-0 text-right text-[12px] ${
                  Math.abs(num(latest?.z) ?? 0) >= 2 ? 'text-red-400 font-semibold' : 'text-zinc-500'
                }`}>
                  {num(latest?.z)?.toFixed(1) ?? '—'}
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Node × hour persistence"
        subtitle="t-statistic of DA−RT by hour of day, 180 days — colour needs |t| ≥ 2, bold ≥ 4"
      >
        {nodeHour.error ? (
          <ErrorNote error={nodeHour.error} />
        ) : nodeHour.rows.length === 0 ? (
          <Empty message="Needs 30+ observations per cell." />
        ) : (
          <div className="overflow-x-auto p-3">
            <table className="tnum w-full min-w-[1000px] text-center text-[11px]">
              <thead>
                <tr className="text-zinc-600">
                  <th className="pr-2 text-left font-medium">point \ HE</th>
                  {Array.from({ length: 24 }, (_, i) => (
                    <th key={i} className="px-0.5 font-medium">{i + 1}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {POINTS.map((p) => (
                  <tr key={p} className="border-t border-line/40">
                    <td className="pr-2 text-left text-zinc-400">{p.replace(/^(HB|LZ)_/, '')}</td>
                    {Array.from({ length: 24 }, (_, i) => {
                      const cell = grid.get(`${p}-${i + 1}`)
                      const t = cell ? num(cell.t_stat) : null
                      return (
                        <td
                          key={i}
                          title={cell ? `${p} HE${i + 1} · mean ${formatUsd(num(cell.mean_spread))} · t ${t?.toFixed(1)} · DA higher ${num(cell.pct_dam_over)}% of ${cell.observations}h` : ''}
                          className={`px-0.5 py-0.5 ${tTone(t)}`}
                        >
                          {t === null ? '·' : t.toFixed(1)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-zinc-600">
              Positive t: day-ahead persistently cleared above real-time in that hour —
              the sell-DA side paid. Cells are blank until an hour has 30 observations.
            </p>
          </div>
        )}
      </Panel>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Spread duration" subtitle="the distribution, because the mean is a lie in a heavy-tailed market">
          {duration.error ? (
            <ErrorNote error={duration.error} />
          ) : duration.rows.length === 0 ? (
            <Empty message="Needs 100+ scored hours per point." />
          ) : (
            <table className="w-full text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">point</th>
                  <th className="px-4 py-2 text-right font-medium">p01</th>
                  <th className="px-4 py-2 text-right font-medium">p50</th>
                  <th className="px-4 py-2 text-right font-medium">p99</th>
                  <th className="px-4 py-2 text-right font-medium">tail ratio</th>
                  <th className="px-4 py-2 text-right font-medium">hours</th>
                </tr>
              </thead>
              <tbody>
                {[...duration.rows]
                  .sort((a, b) => (num(b.tail_ratio) ?? 0) - (num(a.tail_ratio) ?? 0))
                  .map((row) => {
                    const tr = num(row.tail_ratio)
                    return (
                      <tr key={row.settlement_point} className="border-b border-line/60 hover:bg-panel-2">
                        <td className="px-4 py-1.5 text-zinc-300">{row.settlement_point}</td>
                        <td className="tnum px-4 py-1.5 text-right text-sky-300">{formatUsd(num(row.p01))}</td>
                        <td className="tnum px-4 py-1.5 text-right text-zinc-400">{formatUsd(num(row.p50))}</td>
                        <td className="tnum px-4 py-1.5 text-right text-red-400">{formatUsd(num(row.p99))}</td>
                        <td className={`tnum px-4 py-1.5 text-right font-semibold ${
                          (tr ?? 0) > 1.5 ? 'text-red-400' : (tr ?? 0) > 0.7 ? 'text-amber-300' : 'text-emerald-300'
                        }`}>
                          {tr?.toFixed(2) ?? '—'}
                        </td>
                        <td className="tnum px-4 py-1.5 text-right text-zinc-600">{formatCount(row.hours)}</td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          )}
          <p className="px-4 py-2.5 text-[11px] text-zinc-600">
            Tail ratio = |p01| ÷ p99. Above 1 the downside tail is fatter than the upside —
            the shape that ruins anyone selling the spread for premium.
          </p>
        </Panel>

        <Panel title="What the auction charges for uncertainty" subtitle="option minus obligation clearing price, ≥3 auctions, ≥500 MW">
          {vol.error ? (
            <ErrorNote error={vol.error} />
          ) : vol.rows.length === 0 ? (
            <Empty message="Needs CRR auctions with both instruments on a path." />
          ) : (
            <table className="w-full text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">path</th>
                  <th className="px-4 py-2 font-medium">block</th>
                  <th className="px-4 py-2 text-right font-medium">premium</th>
                  <th className="px-4 py-2 text-right font-medium">sd</th>
                  <th className="px-4 py-2 text-right font-medium">MW</th>
                  <th className="px-4 py-2 text-right font-medium">auctions</th>
                </tr>
              </thead>
              <tbody>
                {vol.rows.map((row) => (
                  <tr key={`${row.source}-${row.sink}-${row.time_of_use}`} className="border-b border-line/60 hover:bg-panel-2">
                    <td className="px-4 py-1.5 text-[12px] text-zinc-300">
                      {row.source.slice(0, 12)} → {row.sink.slice(0, 12)}
                    </td>
                    <td className="px-4 py-1.5 text-zinc-500">{row.time_of_use}</td>
                    <td className="tnum px-4 py-1.5 text-right font-semibold text-amber-300">
                      {formatUsd(num(row.avg_premium), 3)}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                      {formatUsd(num(row.premium_sd), 3)}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-500">{formatCount(row.total_mw)}</td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-600">{row.auctions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="px-4 py-2.5 text-[11px] text-zinc-600">
            The market&apos;s own quote for congestion risk per path. Thin premiums on
            wind-exposed off-peak paths are the mismatch worth watching.
          </p>
        </Panel>
      </div>
    </div>
  )
}
