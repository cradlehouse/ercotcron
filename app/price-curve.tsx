// Inline SVG price curve. No chart library: one dependency-free component beats
// 200kB of bundle for a single series.

import { ERCOT_TZ, formatAxis, formatUsd, num, styleFor } from '@/lib/prices'
import type { RtPrice } from '@/lib/supabase'

const W = 1200
const H = 260
const PAD = { top: 16, right: 16, bottom: 26, left: 52 }

const hourFmt = new Intl.DateTimeFormat('en-US', {
  hour: '2-digit',
  hour12: false,
  timeZone: ERCOT_TZ,
})

export function PriceCurve({ rows }: { rows: RtPrice[] }) {
  const points = rows
    .map((row) => ({ t: new Date(row.interval_start).getTime(), v: num(row.price) }))
    .filter((p): p is { t: number; v: number } => Number.isFinite(p.t) && p.v !== null)
    .sort((a, b) => a.t - b.t)

  if (points.length < 2) {
    return (
      <div className="px-4 py-10 text-center text-zinc-500">
        Not enough points to draw a curve yet.
      </div>
    )
  }

  const t0 = points[0].t
  const t1 = points[points.length - 1].t
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

  const x = (t: number) =>
    PAD.left + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.left - PAD.right)
  const y = (v: number) =>
    PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom)

  // Step path: a 15-minute price holds for its whole interval, so interpolating
  // between them would draw prices that never existed.
  const path = points
    .map((p, i) => (i === 0 ? `M ${x(p.t)} ${y(p.v)}` : `H ${x(p.t)} V ${y(p.v)}`))
    .join(' ')
  const area = `${path} V ${y(Math.max(yMin, 0))} H ${x(t0)} Z`

  const last = points[points.length - 1]
  const style = styleFor(last.v)

  const ticks = Array.from({ length: 5 }, (_, i) => yMin + ((yMax - yMin) * i) / 4)
  const hourTicks = points.filter((p, i) => i % Math.ceil(points.length / 8) === 0)

  return (
    <div className="overflow-x-auto p-3">
      <div className="mb-2 flex items-baseline gap-4 px-1">
        <span className={`tnum text-lg font-semibold ${style.text}`}>{formatUsd(last.v)}</span>
        <span className="text-[11px] text-zinc-600">
          high {formatUsd(rawMax)} · low {formatUsd(rawMin)} · {points.length} intervals
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[260px] w-full min-w-[720px]" role="img"
           aria-label="24 hour price curve">
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
          <text
            key={p.t}
            x={x(p.t)}
            y={H - 8}
            textAnchor="middle"
            fill="#52525b"
            fontSize="11"
          >
            {hourFmt.format(new Date(p.t))}
          </text>
        ))}

        <path d={area} fill={style.hex} opacity={0.12} />
        <path d={path} fill="none" stroke={style.hex} strokeWidth={1.5} />
        <circle cx={x(last.t)} cy={y(last.v)} r={3} fill={style.hex} />
      </svg>
    </div>
  )
}
