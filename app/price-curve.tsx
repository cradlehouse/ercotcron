'use client'

// Interactive price curve: step series, crosshair ruler with price readout.
// A client component only for pointer tracking — data arrives from the server
// page as plain rows. Still no chart library: one dependency-free component
// beats 200kB of bundle for a single series.

import { useMemo, useRef, useState } from 'react'

import { ERCOT_TZ, formatAxis, formatUsd, num, styleFor } from '@/lib/prices'
import type { RtPrice } from '@/lib/supabase'

const W = 1200
const H = 280
const PAD = { top: 16, right: 16, bottom: 26, left: 52 }

const hourFmt = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})
const dayHourFmt = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})
const rulerFmt = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})

interface Pt {
  t: number
  v: number
}

export function PriceCurve({ rows }: { rows: RtPrice[] }) {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [cursor, setCursor] = useState<Pt | null>(null)

  const points = useMemo(
    () =>
      rows
        .map((row) => ({ t: new Date(row.interval_start).getTime(), v: num(row.price) }))
        .filter((p): p is Pt => Number.isFinite(p.t) && p.v !== null)
        .sort((a, b) => a.t - b.t),
    [rows],
  )

  if (points.length < 2) {
    return (
      <div className="px-4 py-10 text-center text-zinc-500">
        Not enough points to draw a curve yet.
      </div>
    )
  }

  const t0 = points[0].t
  const t1 = points[points.length - 1].t
  const span = t1 - t0
  const values = points.map((p) => p.v)
  const rawMin = Math.min(...values)
  const rawMax = Math.max(...values)

  // Always include zero: on this data the sign is the story, and a curve that
  // floats above an invisible zero line hides negative pricing entirely.
  const lo = Math.min(0, rawMin)
  const hi = Math.max(rawMax, lo + 1)
  const headroom = (hi - lo) * 0.08
  const yMin = lo - (lo < 0 ? headroom : 0)
  const yMax = hi + headroom

  const x = (t: number) => PAD.left + ((t - t0) / Math.max(1, span)) * (W - PAD.left - PAD.right)
  const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom)

  // Step path: a 15-minute price holds for its whole interval, so interpolating
  // between them would draw prices that never existed.
  const path = points
    .map((p, i) => (i === 0 ? `M ${x(p.t)} ${y(p.v)}` : `H ${x(p.t)} V ${y(p.v)}`))
    .join(' ')
  const area = `${path} V ${y(Math.max(yMin, 0))} H ${x(t0)} Z`

  const last = points[points.length - 1]
  const style = styleFor(last.v)

  const ticks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4)
  const tickEvery = Math.max(1, Math.ceil(points.length / 8))
  const hourTicks = points.filter((_, i) => i % tickEvery === 0)
  const tickFmt = span > 36 * 3600_000 ? dayHourFmt : hourFmt

  // The ruler snaps to the interval the cursor is inside — a step series means
  // "the price at this instant" is the most recent interval's price, not an
  // interpolation between neighbours.
  function track(e: React.PointerEvent<SVGSVGElement>) {
    const el = svgRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const vx = ((e.clientX - rect.left) / rect.width) * W
    const t = t0 + ((vx - PAD.left) / (W - PAD.left - PAD.right)) * span
    if (t < t0 || t > t1) {
      setCursor(null)
      return
    }
    let hit = points[0]
    for (const p of points) {
      if (p.t <= t) hit = p
      else break
    }
    setCursor(hit)
  }

  const cursorStyle = cursor ? styleFor(cursor.v) : style
  // Keep the readout inside the plot: flip to the left of the ruler near the
  // right edge.
  const labelFlip = cursor !== null && x(cursor.t) > W - 230

  return (
    <div className="overflow-x-auto p-3">
      <div className="mb-2 flex items-baseline gap-4 px-1">
        <span className={`tnum text-lg font-semibold ${cursorStyle.text}`}>
          {formatUsd(cursor ? cursor.v : last.v)}
        </span>
        <span className="tnum text-[11px] text-zinc-500">
          {cursor ? rulerFmt.format(new Date(cursor.t)) : 'latest'}
        </span>
        <span className="ml-auto text-[11px] text-zinc-600">
          high {formatUsd(rawMax)} · low {formatUsd(rawMin)} · {points.length} intervals
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-[280px] w-full min-w-[720px] cursor-crosshair select-none"
        role="img"
        aria-label="price curve with crosshair ruler"
        onPointerMove={track}
        onPointerLeave={() => setCursor(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              stroke={Math.abs(v) < 1e-9 ? '#334155' : '#1f242c'}
            />
            <text x={PAD.left - 8} y={y(v) + 4} textAnchor="end" fill="#52525b" fontSize="11">
              {formatAxis(v)}
            </text>
          </g>
        ))}

        {hourTicks.map((p) => (
          <text key={p.t} x={x(p.t)} y={H - 8} textAnchor="middle" fill="#52525b" fontSize="11">
            {tickFmt.format(new Date(p.t))}
          </text>
        ))}

        <path d={area} fill={style.hex} opacity={0.12} />
        <path d={path} fill="none" stroke={style.hex} strokeWidth={1.5} />
        <circle cx={x(last.t)} cy={y(last.v)} r={3} fill={style.hex} />

        {cursor && (
          <g pointerEvents="none">
            <line
              x1={x(cursor.t)}
              x2={x(cursor.t)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="#71717a"
              strokeDasharray="3 3"
            />
            <circle cx={x(cursor.t)} cy={y(cursor.v)} r={4} fill={cursorStyle.hex} />
            <g transform={`translate(${x(cursor.t) + (labelFlip ? -218 : 10)}, ${PAD.top + 2})`}>
              <rect width="208" height="40" rx="4" fill="#0e1013" stroke="#1f242c" />
              <text x="10" y="17" fill={cursorStyle.hex} fontSize="13" fontWeight="600">
                {formatUsd(cursor.v)}
              </text>
              <text x="10" y="32" fill="#71717a" fontSize="11">
                {rulerFmt.format(new Date(cursor.t))} CT
              </text>
            </g>
          </g>
        )}
      </svg>
    </div>
  )
}
