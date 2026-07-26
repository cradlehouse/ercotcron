// What the 15-minute settled average concealed.
//
// The 15-minute SPP is a time-weighted average of the 5-minute SCED prices, so
// a scarcity minute inside an otherwise ordinary interval disappears into the
// mean. spike_ratio is the within-interval peak over that average.

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatDateTime, formatRatio, formatUsd, num, styleFor } from '@/lib/prices'
import { query, type SpikeRow } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

export default async function SpikesPage() {
  const spikes = await query<SpikeRow>((db) =>
    db
      .from('spp_vs_lmp_5min')
      .select('*')
      .not('spike_ratio', 'is', null)
      .order('spike_ratio', { ascending: false })
      .limit(100),
  )

  return (
    <Panel
      title="Concealed scarcity"
      subtitle="highest 5-minute peak relative to the 15-minute settled average, last 7 days"
    >
      {spikes.error ? (
        <ErrorNote error={spikes.error} />
      ) : spikes.rows.length === 0 ? (
        <Empty
          message="No overlapping 15-minute and 5-minute data yet."
          hint="This view needs both the rtm and lmp5 jobs to have run over the same intervals."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left">
            <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
              <tr className="border-b border-line">
                <th className="px-4 py-2 font-medium">settlement point</th>
                <th className="px-4 py-2 font-medium">interval</th>
                <th className="px-4 py-2 text-right font-medium">settled 15-min</th>
                <th className="px-4 py-2 text-right font-medium">5-min peak</th>
                <th className="px-4 py-2 text-right font-medium">5-min low</th>
                <th className="px-4 py-2 text-right font-medium">samples</th>
                <th className="px-4 py-2 text-right font-medium">spike</th>
              </tr>
            </thead>
            <tbody>
              {spikes.rows.map((row) => {
                const settled = num(row.spp_15min)
                const peak = num(row.lmp_5min_max)
                const ratio = num(row.spike_ratio)
                return (
                  <tr
                    key={`${row.settlement_point}-${row.interval_start}`}
                    className="border-b border-line/60 hover:bg-panel-2"
                  >
                    <td className="px-4 py-1.5 text-zinc-300">{row.settlement_point}</td>
                    <td className="tnum px-4 py-1.5 text-zinc-500">
                      {formatDateTime(row.interval_start)}
                    </td>
                    <td className={`tnum px-4 py-1.5 text-right ${styleFor(settled).text}`}>
                      {formatUsd(settled)}
                    </td>
                    <td className={`tnum px-4 py-1.5 text-right ${styleFor(peak).text}`}>
                      {formatUsd(peak)}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                      {formatUsd(num(row.lmp_5min_min))}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-600">
                      {row.lmp_5min_count ?? '—'}
                    </td>
                    <td
                      className={`tnum px-4 py-1.5 text-right font-semibold ${
                        (ratio ?? 0) >= 3
                          ? 'text-red-400'
                          : (ratio ?? 0) >= 1.5
                            ? 'text-amber-300'
                            : 'text-zinc-400'
                      }`}
                    >
                      {formatRatio(ratio)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="px-4 py-2.5 text-[11px] text-zinc-600">
            A sample count below 3 means the interval is still filling — treat its ratio as
            provisional.
          </p>
        </div>
      )}
    </Panel>
  )
}
