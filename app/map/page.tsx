// Schematic price map. Zone and hub markers sit at approximate geographic
// anchors on a simplified Texas outline — ERCOT load-zone boundaries follow
// utility service territories, not geography, so drawing "real" borders would
// be false precision. Markers link to the monitor chart for that point.

import Link from 'next/link'

import { Empty, ErrorNote, Panel } from '@/app/components'
import { formatDateTime, formatUsd, num, styleFor } from '@/lib/prices'
import { query, type LatestPrice } from '@/lib/supabase'

export const dynamic = 'force-dynamic'

// Simplified Texas outline, lon/lat pairs, clockwise from the panhandle NW.
const OUTLINE: Array<[number, number]> = [
  [-103.06, 36.5], [-100.0, 36.5], [-100.0, 34.56], [-99.2, 34.2],
  [-98.1, 34.15], [-96.9, 33.95], [-95.8, 33.85], [-94.6, 33.65],
  [-94.04, 33.55], [-94.04, 31.0], [-93.7, 30.0], [-93.85, 29.7],
  [-94.9, 29.35], [-95.3, 28.9], [-96.4, 28.4], [-97.15, 27.6],
  [-97.15, 26.0], [-97.4, 25.85], [-98.3, 26.1], [-99.1, 26.4],
  [-99.5, 27.5], [-100.4, 28.3], [-101.4, 29.75], [-102.3, 29.9],
  [-103.1, 28.98], [-104.5, 29.6], [-104.9, 30.6], [-106.5, 31.75],
  [-106.6, 32.0], [-103.06, 32.0],
]

// Approximate anchors. Zones render as squares, hubs as circles.
const MARKERS: Array<{ point: string; lon: number; lat: number; kind: 'zone' | 'hub' }> = [
  { point: 'HB_PAN', lon: -101.8, lat: 35.2, kind: 'hub' },
  { point: 'HB_WEST', lon: -102.1, lat: 31.9, kind: 'hub' },
  { point: 'HB_NORTH', lon: -98.1, lat: 33.5, kind: 'hub' },
  { point: 'HB_HOUSTON', lon: -94.9, lat: 29.55, kind: 'hub' },
  { point: 'HB_SOUTH', lon: -98.2, lat: 28.35, kind: 'hub' },
  { point: 'LZ_WEST', lon: -100.5, lat: 31.6, kind: 'zone' },
  { point: 'LZ_NORTH', lon: -96.9, lat: 32.85, kind: 'zone' },
  { point: 'LZ_RAYBN', lon: -95.4, lat: 33.15, kind: 'zone' },
  { point: 'LZ_HOUSTON', lon: -95.55, lat: 29.9, kind: 'zone' },
  { point: 'LZ_AEN', lon: -97.75, lat: 30.27, kind: 'zone' },
  { point: 'LZ_CPS', lon: -98.55, lat: 29.4, kind: 'zone' },
  { point: 'LZ_LCRA', lon: -98.7, lat: 30.7, kind: 'zone' },
  { point: 'LZ_SOUTH', lon: -97.9, lat: 27.3, kind: 'zone' },
]

// System-wide averages have no location; they get chips, not coordinates.
const SYNTHETIC = ['HB_HUBAVG', 'HB_BUSAVG']

const W = 760
const H = 640
const PAD = 30
const LON = { min: -106.8, max: -93.5 }
const LAT = { min: 25.7, max: 36.7 }

function x(lon: number): number {
  return PAD + ((lon - LON.min) / (LON.max - LON.min)) * (W - 2 * PAD)
}
function y(lat: number): number {
  return PAD + ((LAT.max - lat) / (LAT.max - LAT.min)) * (H - 2 * PAD)
}

export default async function MapPage() {
  const latest = await query<LatestPrice>((db) => db.from('latest_prices').select('*'))
  const byPoint = new Map(latest.rows.map((r) => [r.settlement_point, r]))

  const outline = OUTLINE.map(
    ([lon, lat], i) => `${i === 0 ? 'M' : 'L'} ${x(lon).toFixed(1)} ${y(lat).toFixed(1)}`,
  ).join(' ') + ' Z'

  const asOf = latest.rows[0]?.interval_start

  return (
    <Panel
      title="Price map"
      subtitle={`schematic — markers at approximate zone and hub locations${
        asOf ? ` · interval ${formatDateTime(asOf)}` : ''
      }`}
      right={
        <div className="flex gap-2">
          {SYNTHETIC.map((p) => {
            const row = byPoint.get(p)
            const price = row ? num(row.price) : null
            const s = styleFor(price)
            return (
              <Link
                key={p}
                href={`/?point=${p}`}
                className={`rounded border px-2.5 py-1 text-[11px] transition-all hover:brightness-125 ${s.bg} ${s.border}`}
              >
                <span className="text-zinc-500">{p.replace('HB_', '')}</span>{' '}
                <span className={`tnum font-semibold ${s.text}`}>{formatUsd(price)}</span>
              </Link>
            )
          })}
        </div>
      }
    >
      {latest.error ? (
        <ErrorNote error={latest.error} />
      ) : latest.rows.length === 0 ? (
        <Empty message="No prices ingested yet." />
      ) : (
        <div className="flex justify-center p-3">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="h-auto w-full max-w-[760px]"
            role="img"
            aria-label="schematic map of ERCOT hub and zone prices"
          >
            <path d={outline} fill="#14171c" stroke="#2a313b" strokeWidth="1.5" />

            {MARKERS.map((m) => {
              const row = byPoint.get(m.point)
              const price = row ? num(row.price) : null
              const s = styleFor(price)
              const cx = x(m.lon)
              const cy = y(m.lat)
              const label = m.point.replace(/^(LZ|HB)_/, '')
              return (
                <Link key={m.point} href={`/?point=${m.point}`}>
                  {/* group-scoped hover: ring + label brighten together */}
                  <g className="group cursor-pointer">
                    {m.kind === 'hub' ? (
                      <circle
                        cx={cx}
                        cy={cy}
                        r={9}
                        fill={s.hex}
                        fillOpacity={0.25}
                        stroke={s.hex}
                        strokeWidth={1.5}
                        className="transition-all group-hover:fill-opacity-60"
                      />
                    ) : (
                      <rect
                        x={cx - 8}
                        y={cy - 8}
                        width={16}
                        height={16}
                        rx={3}
                        fill={s.hex}
                        fillOpacity={0.25}
                        stroke={s.hex}
                        strokeWidth={1.5}
                        className="transition-all group-hover:fill-opacity-60"
                      />
                    )}
                    <text
                      x={cx}
                      y={cy - 14}
                      textAnchor="middle"
                      fontSize="11"
                      fill="#a1a1aa"
                      className="group-hover:fill-zinc-100"
                    >
                      {label}
                      {m.kind === 'hub' ? ' hub' : ''}
                    </text>
                    <text
                      x={cx}
                      y={cy + 26}
                      textAnchor="middle"
                      fontSize="12"
                      fontWeight="600"
                      fill={s.hex}
                      className="tnum"
                    >
                      {formatUsd(price)}
                    </text>
                  </g>
                </Link>
              )
            })}

            <g transform={`translate(${PAD}, ${H - 58})`} fontSize="11" fill="#52525b">
              <circle cx={6} cy={0} r={6} fill="none" stroke="#52525b" strokeWidth="1.5" />
              <text x={18} y={4}>trading hub</text>
              <rect x={0} y={14} width={12} height={12} rx={2} fill="none" stroke="#52525b" strokeWidth="1.5" />
              <text x={18} y={24}>load zone</text>
              <text x={0} y={44} fill="#3f3f46">click a marker to chart it · positions approximate</text>
            </g>
          </svg>
        </div>
      )}
    </Panel>
  )
}
