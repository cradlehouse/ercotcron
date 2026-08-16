// Live monitor: latest price per settlement point, an interactive curve with
// point selection, range presets, and a custom date range.

import Link from 'next/link'

import { Empty, ErrorNote, Freshness, Panel } from '@/app/components'
import { PriceCurve } from '@/app/price-curve'
import {
  formatDateTime,
  formatUsd,
  hoursAgoIso,
  num,
  scaleFor,
  styleFor,
  styleForTone,
} from '@/lib/prices'
import { readThresholds, thresholdParams } from '@/lib/thresholds'
import { ThresholdBar } from '@/app/threshold-bar'
import { query, type FeedLatency, type LatestPrice, type RtPrice } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

const DEFAULT_POINT = 'HB_HUBAVG'
const RANGES = [
  { key: '6h', label: '6h', hours: 6 },
  { key: '24h', label: '24h', hours: 24 },
  { key: '3d', label: '3d', hours: 72 },
  { key: '7d', label: '7d', hours: 168 },
] as const

const POINT_RE = /^[A-Z0-9_]{2,30}$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

interface Params extends Record<string, string | undefined> {
  point?: string
  range?: string
  from?: string
  to?: string
  reset?: string
  cb?: string
  da?: string
  el?: string
  sc?: string
  ex?: string
}

export default async function MonitorPage({
  searchParams,
}: {
  searchParams: Promise<Params>
}) {
  const params = await searchParams
  const point = POINT_RE.test(params.point ?? '') ? params.point! : DEFAULT_POINT

  // A custom date range (ERCOT operating days, via delivery_date — no timezone
  // arithmetic) wins over the hour presets when both are present and valid.
  const from = DATE_RE.test(params.from ?? '') ? params.from! : null
  const to = DATE_RE.test(params.to ?? '') ? params.to! : null
  const custom = from && to && from <= to ? { from, to } : null
  const range = RANGES.find((r) => r.key === params.range) ?? RANGES[1]

  // `reset` wins over any level params the reset button left in the form.
  const thresholds = readThresholds(params.reset ? {} : params)
  const bands = thresholds
  const levelParams = thresholdParams(thresholds)

  const qs = (overrides: Record<string, string | undefined>) => {
    const merged: Record<string, string | undefined> = {
      point,
      range: custom ? undefined : range.key,
      from: custom?.from,
      to: custom?.to,
      ...levelParams,
      ...overrides,
    }
    const parts = Object.entries(merged)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(v!)}`)
    return parts.length ? `/?${parts.join('&')}` : '/'
  }

  const [latest, curve, latency] = await Promise.all([
    query<LatestPrice>((db) =>
      db.from('latest_prices').select('*').order('settlement_point'),
    ),
    query<RtPrice>((db) => {
      let q = db
        .from('rt_spp')
        .select('settlement_point,interval_start,price')
        .eq('settlement_point', point)
      q = custom
        ? q.gte('delivery_date', custom.from).lte('delivery_date', custom.to)
        : q.gte('interval_start', hoursAgoIso(range.hours))
      return q.order('interval_start').limit(4000)
    }),
    query<FeedLatency>((db) =>
      db.from('feed_latency').select('*').order('hour', { ascending: false }).limit(72),
    ),
  ])

  const lastByFeed = new Map<string, string | null>()
  for (const row of latency.rows) {
    if (!lastByFeed.has(row.feed)) lastByFeed.set(row.feed, row.last_ingest)
  }
  const feeds = ['rt_spp', 'rt_lmp_5min', 'dam_spp']

  const rangeLabel = custom ? `${custom.from} → ${custom.to}` : `last ${range.label}`

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {feeds.map((feed) => (
          <Freshness key={feed} label={feed} at={lastByFeed.get(feed) ?? null} />
        ))}
      </div>

      <Panel title="Your levels" subtitle="colour bands and trade triggers — shared in the URL">
        <ThresholdBar
          thresholds={thresholds}
          hidden={{
            point,
            ...(custom ? { from: custom.from, to: custom.to } : { range: range.key }),
          }}
        />
      </Panel>

      <Panel
        title="Latest settled price"
        subtitle="15-minute real-time SPP, $/MWh — click a point to chart it"
        right={
          <div className="flex flex-wrap gap-3">
            {scaleFor(bands).map(({ tone, range: label }) => {
              const s = styleForTone(tone)
              return (
                <span key={tone} className="flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.hex }} />
                  {label}
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
              const s = styleFor(price, bands)
              const active = row.settlement_point === point
              // Trade triggers are independent of the colour bands: a price can
              // be an ordinary green and still be below your charge level.
              const signal =
                price === null
                  ? null
                  : price < thresholds.chargeBelow
                    ? 'charge'
                    : price > thresholds.dischargeAbove
                      ? 'discharge'
                      : null
              return (
                <Link
                  key={row.settlement_point}
                  href={qs({ point: row.settlement_point })}
                  aria-current={active ? 'true' : undefined}
                  className={`rounded border px-3 py-2.5 transition-all duration-100 ${s.bg} ${
                    active
                      ? 'border-zinc-300/70 ring-1 ring-zinc-300/40'
                      : `${s.border} hover:border-zinc-400/60 hover:brightness-125`
                  }`}
                >
                  <div className="flex items-baseline gap-1.5">
                    <span className="truncate text-[11px] text-zinc-500">
                      {row.settlement_point}
                    </span>
                    {signal && (
                      <span
                        className={`ml-auto shrink-0 rounded px-1 text-[9px] font-semibold uppercase tracking-wide ${
                          signal === 'charge'
                            ? 'bg-sky-500/20 text-sky-300'
                            : 'bg-amber-500/20 text-amber-300'
                        }`}
                      >
                        {signal}
                      </span>
                    )}
                  </div>
                  <div className={`tnum mt-0.5 text-lg font-semibold ${s.text}`}>
                    {formatUsd(price)}
                  </div>
                  <div className="tnum text-[11px] text-zinc-600">
                    {formatDateTime(row.interval_start)}
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </Panel>

      <Panel
        title={`${point} — ${rangeLabel}`}
        subtitle="15-minute settled SPP · hover for the ruler"
        right={
          <div className="flex items-center gap-3">
            <div className="flex overflow-hidden rounded border border-line">
              {RANGES.map((r) => (
                <Link
                  key={r.key}
                  href={qs({ range: r.key, from: undefined, to: undefined })}
                  className={`px-2.5 py-1 text-[11px] transition-colors ${
                    !custom && r.key === range.key
                      ? 'bg-panel-2 text-zinc-200'
                      : 'text-zinc-500 hover:text-zinc-200'
                  }`}
                >
                  {r.label}
                </Link>
              ))}
            </div>
            <form method="get" action="/" className="flex items-center gap-1.5">
              <input type="hidden" name="point" value={point} />
              <input
                type="date"
                name="from"
                defaultValue={custom?.from}
                required
                className="rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] text-zinc-300 [color-scheme:dark]"
              />
              <span className="text-[11px] text-zinc-600">→</span>
              <input
                type="date"
                name="to"
                defaultValue={custom?.to}
                required
                className="rounded border border-line bg-panel-2 px-1.5 py-0.5 text-[11px] text-zinc-300 [color-scheme:dark]"
              />
              <button
                type="submit"
                className="rounded border border-line px-2 py-0.5 text-[11px] text-zinc-400 transition-colors hover:border-zinc-500 hover:text-zinc-200"
              >
                go
              </button>
            </form>
          </div>
        }
      >
        {curve.error ? (
          <ErrorNote error={curve.error} />
        ) : curve.rows.length === 0 ? (
          <Empty message={`No 15-minute prices for ${point} in this window.`} />
        ) : (
          <PriceCurve rows={curve.rows} />
        )}
      </Panel>
    </div>
  )
}
