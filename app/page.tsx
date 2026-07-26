// Live monitor: latest price per settlement point, a 24-hour curve, freshness.

import { Empty, ErrorNote, Freshness, Panel } from '@/app/components'
import { PriceCurve } from '@/app/price-curve'
import {
  SCALE,
  formatDateTime,
  formatUsd,
  hoursAgoIso,
  num,
  styleFor,
  styleForTone,
} from '@/lib/prices'
import { query, type FeedLatency, type LatestPrice, type RtPrice } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

const CURVE_POINT = 'HB_HUBAVG'

export default async function MonitorPage() {
  const [latest, curve, latency] = await Promise.all([
    query<LatestPrice>((db) =>
      db.from('latest_prices').select('*').order('settlement_point'),
    ),
    query<RtPrice>((db) =>
      db
        .from('rt_spp')
        .select('settlement_point,interval_start,price')
        .eq('settlement_point', CURVE_POINT)
        .gte('interval_start', hoursAgoIso(24))
        .order('interval_start'),
    ),
    query<FeedLatency>((db) =>
      db.from('feed_latency').select('*').order('hour', { ascending: false }).limit(72),
    ),
  ])

  // feed_latency is per hour; the newest row per feed is the freshness signal.
  const lastByFeed = new Map<string, string | null>()
  for (const row of latency.rows) {
    if (!lastByFeed.has(row.feed)) lastByFeed.set(row.feed, row.last_ingest)
  }
  const feeds = ['rt_spp', 'rt_lmp_5min', 'dam_spp']

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {feeds.map((feed) => (
          <Freshness key={feed} label={feed} at={lastByFeed.get(feed) ?? null} />
        ))}
      </div>

      <Panel
        title="Latest settled price"
        subtitle="15-minute real-time SPP, $/MWh"
        right={
          <div className="flex flex-wrap gap-3">
            {SCALE.map(({ tone, range }) => {
              const style = styleForTone(tone)
              return (
                <span key={tone} className="flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <span
                    className="inline-block h-2 w-2 rounded-sm"
                    style={{ background: style.hex }}
                  />
                  {range}
                </span>
              )
            })}
          </div>
        }
      >
        {latest.error ? (
          <ErrorNote error={latest.error} />
        ) : latest.rows.length === 0 ? (
          <Empty
            message="No prices ingested yet."
            hint="Seed the first pull with: python scripts/run_ingest.py rtm"
          />
        ) : (
          <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-5">
            {latest.rows.map((row) => {
              const price = num(row.price)
              const style = styleFor(price)
              return (
                <div
                  key={row.settlement_point}
                  className={`rounded border px-3 py-2.5 ${style.bg} ${style.border}`}
                >
                  <div className="truncate text-[11px] text-zinc-500">{row.settlement_point}</div>
                  <div className={`tnum mt-0.5 text-lg font-semibold ${style.text}`}>
                    {formatUsd(price)}
                  </div>
                  <div className="tnum text-[11px] text-zinc-600">
                    {formatDateTime(row.interval_start)}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>

      <Panel title={`${CURVE_POINT} — last 24 hours`} subtitle="15-minute settled SPP">
        {curve.error ? (
          <ErrorNote error={curve.error} />
        ) : curve.rows.length === 0 ? (
          <Empty message={`No 15-minute prices for ${CURVE_POINT} in the last 24 hours.`} />
        ) : (
          <PriceCurve rows={curve.rows} />
        )}
      </Panel>
    </div>
  )
}
