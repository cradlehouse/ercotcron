'use client'
// The market flow field: every monthly-auction path as a faint strand,
// clearing-price buckets as labeled lines. Cumulative return per $1 bid —
// the whole population, not a curated average. NYT-flow-field construction
// on the Dispatch palette.
//
// Dataviz rules applied: one y-axis; sequential warm ramp (price magnitude,
// bright=cheap → dark red=expensive) with monotonic lightness on the ink
// surface; every bucket line direct-labeled + legend; text in ink tokens;
// zero-line emphasized; hover crosshair with per-bucket values; a table view
// below the plot. Strands are paths, never holders (methodology §10).
import { useEffect, useMemo, useRef, useState } from 'react'

type Flow = {
  months: string[]
  buckets: { label: string; series: number[]; paths: number }[]
  strands: { b: number; y: (number | null)[] }[]
  n_paths: number
  generated_at: string
}

// Validated sequential ramp on #15242c: lightness 0.91→0.55 monotonic,
// contrast ≥3:1 each step. Identity never rides on color alone — every
// bucket line carries a direct label.
const RAMP = ['#f6e27a', '#f2c14e', '#eda63a', '#d97b2c', '#c04a1d']

const W = 920, H = 460, M = { t: 18, r: 128, b: 34, l: 46 }

export function MarketFlowChart() {
  const [data, setData] = useState<Flow | null>(null)
  const [hoverMi, setHoverMi] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    fetch('/api/artifact/market_flow')
      .then(r => (r.ok ? r.json() : fetch('/market_flow.json').then(f => f.json())))
      .then(setData)
      .catch(() => fetch('/market_flow.json').then(f => f.json()).then(setData).catch(() => null))
  }, [])

  const geom = useMemo(() => {
    if (!data) return null
    const n = data.months.length
    // Domain from the BUCKET lines (the heroes); strands may run hot early
    // in their life and simply exit the frame through the clip, NYT-style,
    // instead of gluing to a clamp.
    const bys = data.buckets.flatMap(b => b.series)
    const pad = 0.15
    const yMin = Math.min(...bys) - pad
    const yMax = Math.max(...bys) + pad
    const x = (mi: number) => M.l + (mi / (n - 1)) * (W - M.l - M.r)
    const y = (v: number) =>
      M.t + (1 - (v - yMin) / (yMax - yMin)) * (H - M.t - M.b)
    const line = (series: (number | null)[]) => {
      let d = ''
      series.forEach((v, mi) => {
        if (v === null) return
        d += (d ? 'L' : 'M') + x(mi).toFixed(1) + ',' + y(v).toFixed(1)
      })
      return d
    }
    return { x, y, line, yMin, yMax, n }
  }, [data])

  // Direct labels at line ends, nudged apart so they never collide.
  const labels = useMemo(() => {
    if (!data || !geom) return []
    const raw = data.buckets.map((b, bi) => ({
      bi, label: b.label, v: b.series[b.series.length - 1],
      yPos: geom.y(b.series[b.series.length - 1]),
    })).sort((a, b) => a.yPos - b.yPos)
    for (let i = 1; i < raw.length; i++) {
      if (raw[i].yPos - raw[i - 1].yPos < 16) raw[i].yPos = raw[i - 1].yPos + 16
    }
    return raw
  }, [data, geom])

  if (!data || !geom) {
    return <div className="h-[300px] rounded border border-line bg-panel/40" aria-hidden />
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const px = ((e.clientX - rect.left) / rect.width) * W
    const mi = Math.round(((px - M.l) / (W - M.l - M.r)) * (geom.n - 1))
    setHoverMi(mi >= 0 && mi < geom.n ? mi : null)
  }

  const zeroY = geom.y(0)
  return (
    <figure className="m-0">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none"
           role="img" aria-label="Cumulative return per dollar bid, by clearing-price bucket, across ERCOT monthly CRR auctions"
           onMouseMove={onMove} onMouseLeave={() => setHoverMi(null)}>
        {/* recessive grid + emphasized zero line */}
        {[-0.75, -0.5, -0.25, 0.25, 0.5, 1, 1.5, 2, 2.5].filter(v => v > geom.yMin && v < geom.yMax).map(v => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={geom.y(v)} y2={geom.y(v)} stroke="#22333c" strokeWidth={1} />
            <text x={M.l - 6} y={geom.y(v) + 3} textAnchor="end" fontSize={10} fill="#61767e">
              {v > 0 ? `+${Math.round(v * 100)}%` : `−${Math.round(-v * 100)}%`}
            </text>
          </g>
        ))}
        <line x1={M.l} x2={W - M.r} y1={zeroY} y2={zeroY} stroke="#3a4f58" strokeWidth={1.5} />
        <text x={M.l - 6} y={zeroY + 3} textAnchor="end" fontSize={10} fill="#93a6ab">0%</text>

        <clipPath id="flow-plot"><rect x={M.l} y={M.t} width={W - M.l - M.r} height={H - M.t - M.b} /></clipPath>
        {/* the population: faint strands (clipped — hot early-life ratios exit the frame) */}
        <g fill="none" strokeWidth={1} clipPath="url(#flow-plot)">
          {data.strands.map((s, i) => (
            <path key={i} d={geom.line(s.y)} stroke={RAMP[s.b]} strokeOpacity={0.07} />
          ))}
        </g>

        {/* bucket aggregates: 2px, labeled */}
        <g fill="none" strokeWidth={2}>
          {data.buckets.map((b, bi) => (
            <path key={bi} d={geom.line(b.series)} stroke={RAMP[bi]}
              strokeLinecap="round"
              style={{ filter: 'drop-shadow(0 0 4px rgba(0,0,0,0.6))' }} />
          ))}
        </g>
        {labels.map(l => (
          <text key={l.bi} x={W - M.r + 8} y={l.yPos + 4} fontSize={11.5} fill="#dbe4e6">
            <tspan fill={RAMP[l.bi]}>●</tspan> {l.label}
            <tspan fill="#93a6ab"> {l.v >= 0 ? '+' : '−'}{Math.abs(l.v * 100).toFixed(0)}%</tspan>
          </text>
        ))}

        {/* x axis: sparse month ticks */}
        {data.months.map((m, mi) => (mi % 4 === 0 || mi === geom.n - 1) && (
          <text key={m} x={geom.x(mi)} y={H - 12} textAnchor="middle" fontSize={10} fill="#61767e">
            {m}
          </text>
        ))}

        {/* hover crosshair + readout */}
        {hoverMi !== null && (
          <g pointerEvents="none">
            <line x1={geom.x(hoverMi)} x2={geom.x(hoverMi)} y1={M.t} y2={H - M.b}
              stroke="#93a6ab" strokeWidth={1} strokeDasharray="3 3" strokeOpacity={0.6} />
            {data.buckets.map((b, bi) => (
              <circle key={bi} cx={geom.x(hoverMi)} cy={geom.y(b.series[hoverMi])} r={3.5}
                fill={RAMP[bi]} stroke="#15242c" strokeWidth={2} />
            ))}
            <g transform={`translate(${Math.min(geom.x(hoverMi) + 10, W - M.r - 168)}, ${M.t + 6})`}>
              <rect width={160} height={16 + data.buckets.length * 15} rx={5} fill="#1e3038" stroke="#2c424c" />
              <text x={8} y={13} fontSize={10.5} fill="#93a6ab">{data.months[hoverMi]} · return per $1 paid in</text>
              {data.buckets.map((b, bi) => (
                <text key={bi} x={8} y={28 + bi * 15} fontSize={10.5} fill="#dbe4e6">
                  <tspan fill={RAMP[bi]}>●</tspan> {b.label}:{' '}
                  {b.series[hoverMi] >= 0 ? '+' : '−'}{Math.abs(b.series[hoverMi] * 100).toFixed(0)}%
                </text>
              ))}
            </g>
          </g>
        )}
      </svg>
      <figcaption className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[11px] text-[#61767e]">
        <span>
          {data.n_paths.toLocaleString()} paths across {data.months.length} settled months —
          each faint strand is one path&apos;s running return per $1 paid in (cumulative payout
          over cumulative premium); heavy lines are the clearing-price buckets on the same basis.
        </span>
        <span>Paths, never holders. Historical description, not a forecast.</span>
        <span>window {data.months[0]} → {data.months[data.months.length - 1]} · run {data.generated_at?.slice(0, 10)}</span>
      </figcaption>
      {/* table view — the same facts, readable without the graphic */}
      <table className="mt-3 w-full max-w-lg border-collapse text-[11.5px]">
        <thead>
          <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#61767e]">
            <th className="py-1 pr-3 font-medium">Cleared at</th>
            <th className="py-1 pr-3 text-right font-medium">Paths</th>
            <th className="py-1 text-right font-medium">Return per $1 paid in</th>
          </tr>
        </thead>
        <tbody>
          {data.buckets.map((b, bi) => {
            const v = b.series[b.series.length - 1]
            return (
              <tr key={bi} className="border-b border-line/50 last:border-0 text-[#93a6ab]">
                <td className="py-1 pr-3"><span style={{ color: RAMP[bi] }}>●</span> {b.label}</td>
                <td className="py-1 pr-3 text-right tnum">{b.paths.toLocaleString()}</td>
                <td className={`py-1 text-right tnum ${v >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {v >= 0 ? '+' : '−'}{Math.abs(v * 100).toFixed(0)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </figure>
  )
}
