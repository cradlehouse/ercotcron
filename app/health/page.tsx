// Operational page: did the crons run, did they return anything, what changed.

import { Empty, ErrorNote, Panel, Stat, StatusChip } from '@/app/components'
import { formatCount, formatDateTime, formatDuration, formatRelative, num } from '@/lib/prices'
import {
  query,
  type FeedLatency,
  type IngestRun,
  type RevisionCount,
} from '@/lib/supabase'

export const dynamic = 'force-dynamic'

interface Gap {
  settlement_point: string
  interval_start: string
}

export default async function HealthPage() {
  const [runs, gaps, revisions, latency] = await Promise.all([
    query<IngestRun>((db) =>
      db.from('ingest_runs').select('*').order('started_at', { ascending: false }).limit(40),
    ),
    query<Gap>((db) => db.from('rt_spp_gaps').select('*').limit(500)),
    query<RevisionCount>((db) =>
      db.from('revision_counts').select('*').order('hour', { ascending: false }).limit(48),
    ),
    query<FeedLatency>((db) =>
      db.from('feed_latency').select('*').order('hour', { ascending: false }).limit(24),
    ),
  ])

  const failing = runs.rows.filter((r) => r.status === 'error').length
  const emptyRuns = runs.rows.filter((r) => r.status === 'empty').length
  const totalRevisions = revisions.rows.reduce((sum, r) => sum + (num(r.revisions) ?? 0), 0)

  // A failed query must never render as a reassuring green zero — on a
  // monitoring page, "we could not tell" and "all clear" are opposite answers.
  const unknown = { value: '—', tone: 'text-zinc-600', note: 'query failed' }
  const stat = (
    failed: string | null,
    value: number,
    good: string,
    bad: string,
    note: string,
  ) => (failed ? unknown : { value: formatCount(value), tone: value ? bad : good, note })

  const runStat = (value: number, bad: string, note: string) =>
    stat(runs.error, value, 'text-emerald-300', bad, note)

  const failedStat = runStat(failing, 'text-red-400', 'of the last 40')
  const emptyStat = runStat(emptyRuns, 'text-amber-300', 'zero rows — check endpoint params')
  const gapStat = stat(
    gaps.error, gaps.rows.length, 'text-emerald-300', 'text-amber-300', 'last 3 days',
  )
  const revisionStat = revisions.error
    ? unknown
    : { value: formatCount(totalRevisions), tone: 'text-zinc-200', note: 'last 7 days' }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="failed runs" {...failedStat} />
        <Stat label="empty runs" {...emptyStat} />
        <Stat label="15-min gaps" {...gapStat} />
        <Stat label="revisions" {...revisionStat} />
      </div>

      <Panel title="Ingest runs" subtitle="most recent first">
        {runs.error ? (
          <ErrorNote error={runs.error} />
        ) : runs.rows.length === 0 ? (
          <Empty
            message="No ingest runs recorded."
            hint="Nothing has run yet. Start the Render service, or run: python scripts/run_ingest.py dam"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">job</th>
                  <th className="px-4 py-2 font-medium">started</th>
                  <th className="px-4 py-2 font-medium">status</th>
                  <th className="px-4 py-2 text-right font-medium">seen</th>
                  <th className="px-4 py-2 text-right font-medium">new</th>
                  <th className="px-4 py-2 text-right font-medium">revised</th>
                  <th className="px-4 py-2 text-right font-medium">took</th>
                  <th className="px-4 py-2 font-medium">error</th>
                </tr>
              </thead>
              <tbody>
                {runs.rows.map((run) => {
                  const took =
                    run.finished_at
                      ? (new Date(run.finished_at).getTime() -
                          new Date(run.started_at).getTime()) / 1000
                      : null
                  return (
                    <tr key={run.id} className="border-b border-line/60 hover:bg-panel-2">
                      <td className="px-4 py-1.5 text-zinc-300">{run.job}</td>
                      <td className="tnum px-4 py-1.5 text-zinc-500">
                        {formatDateTime(run.started_at)}
                        <span className="ml-2 text-zinc-700">{formatRelative(run.started_at)}</span>
                      </td>
                      <td className="px-4 py-1.5">
                        <StatusChip status={run.status} />
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatCount(run.rows_seen)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatCount(run.rows_inserted)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                        {formatCount(run.rows_revised)}
                      </td>
                      <td className="tnum px-4 py-1.5 text-right text-zinc-500">
                        {formatDuration(took)}
                      </td>
                      <td className="max-w-[280px] truncate px-4 py-1.5 text-red-400/80">
                        {run.error ?? ''}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Publication lag" subtitle="by hour, from interval close to ingest">
          {latency.error ? (
            <ErrorNote error={latency.error} />
          ) : latency.rows.length === 0 ? (
            <Empty message="No latency data yet." />
          ) : (
            <table className="w-full text-left">
              <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                <tr className="border-b border-line">
                  <th className="px-4 py-2 font-medium">feed</th>
                  <th className="px-4 py-2 font-medium">hour</th>
                  <th className="px-4 py-2 text-right font-medium">rows</th>
                  <th className="px-4 py-2 text-right font-medium">avg lag</th>
                </tr>
              </thead>
              <tbody>
                {latency.rows.map((row) => (
                  <tr key={`${row.feed}-${row.hour}`} className="border-b border-line/60">
                    <td className="px-4 py-1.5 text-zinc-400">{row.feed}</td>
                    <td className="tnum px-4 py-1.5 text-zinc-500">{formatDateTime(row.hour)}</td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                      {formatCount(row.rows)}
                    </td>
                    <td className="tnum px-4 py-1.5 text-right text-zinc-400">
                      {formatDuration(num(row.avg_lag_seconds))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title="Missing 15-minute intervals" subtitle="last 3 days">
          {gaps.error ? (
            <ErrorNote error={gaps.error} />
          ) : gaps.rows.length === 0 ? (
            <Empty message="No gaps. Every expected interval is present." />
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              <table className="w-full text-left">
                <thead className="text-[11px] uppercase tracking-wide text-zinc-600">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2 font-medium">settlement point</th>
                    <th className="px-4 py-2 font-medium">interval</th>
                  </tr>
                </thead>
                <tbody>
                  {gaps.rows.slice(0, 200).map((gap) => (
                    <tr
                      key={`${gap.settlement_point}-${gap.interval_start}`}
                      className="border-b border-line/60"
                    >
                      <td className="px-4 py-1.5 text-zinc-400">{gap.settlement_point}</td>
                      <td className="tnum px-4 py-1.5 text-amber-300/80">
                        {formatDateTime(gap.interval_start)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="px-4 py-2 text-[11px] text-zinc-600">
                Repair with: python scripts/run_ingest.py lmp5 --since-minutes 720
              </p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
