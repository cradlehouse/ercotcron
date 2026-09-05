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

type Strand = { b: number; y: (number | null)[]; l?: string; cp?: number }
type Flow = {
  months: string[]
  buckets: { label: string; series: number[]; paths: number }[]
  strands: Strand[]
  n_paths: number
  generated_at: string
}

// Validated sequential ramp on #15242c: lightness 0.91→0.55 monotonic,
// contrast ≥3:1 each step. Identity never rides on color alone — every
// bucket line carries a direct label.
const RAMP = ['#f6e27a', '#f2c14e', '#eda63a', '#d97b2c', '#c04a1d']

export function MarketFlowChart() {
  const [data, setData] = useState<Flow | null>(null)
  const [hoverMi, setHoverMi] = useState<number | null>(null)
  const [hoverStrand, setHoverStrand] = useState<number | null>(null)
  const [pinned, setPinned] = useState<number | null>(null)
  const [boxW, setBoxW] = useState(920)
  const svgRef = useRef<SVGSVGElement>(null)
  const wrapRef = useRef<HTMLElement>(null)

  useEffect(() => {
    // Depends on `data`: before the payload arrives only the placeholder is
    // mounted and wrapRef is null — attaching on [] would observe nothing.
    if (!wrapRef.current) return
    const ro = new ResizeObserver(([e]) => setBoxW(e.contentRect.width))
    ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [data])

  // Text is drawn in viewBox units: on a narrow box a 920-unit canvas shrinks
  // the type into illegibility. Compact mode uses a SMALLER canvas (type
  // renders larger), drops the right label gutter (the table below is the
  // legend), and thins the ticks.
  const compact = boxW < 700
  const W = compact ? 440 : 920
  const H = compact ? 400 : 460
  const M = compact ? { t: 14, r: 14, b: 30, l: 40 } : { t: 18, r: 128, b: 34, l: 46 }

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
    // Strand variant: draw only in-band SEGMENTS. Early-life ratios and
    // off-scale swings otherwise transit the frame as vertical streaks —
    // a strand breaks where it leaves the visible band and restarts where
    // it re-enters, so the field is curves, not hay.
    const lo = yMin - 0.05, hi = yMax + 0.05
    const strandLine = (series: (number | null)[]) => {
      let d = ''
      let pen = false
      let lived = 0
      series.forEach((v, mi) => {
        if (v === null) { return }
        lived += 1
        if (lived <= 2 || v < lo || v > hi) { pen = false; return }
        d += (pen ? 'L' : 'M') + x(mi).toFixed(1) + ',' + y(v).toFixed(1)
        pen = true
      })
      return d
    }
    return { x, y, line, strandLine, yMin, yMax, n }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, compact])

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

  // Interpolated y of a strand at a fractional month — for nearest-line hit
  // testing, so 2,000 one-pixel paths are hoverable without 2,000 listeners.
  const strandYAt = (st: Strand, mif: number): number | null => {
    const i0 = Math.floor(mif), i1 = Math.min(i0 + 1, st.y.length - 1)
    const a = st.y[i0], b = st.y[i1]
    if (a === null || a === undefined) return null
    if (b === null || b === undefined) return a
    return a + (b - a) * (mif - i0)
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || !data) return
    const px = ((e.clientX - rect.left) / rect.width) * W
    const py = ((e.clientY - rect.top) / rect.height) * H
    const mif = Math.max(0, Math.min(geom.n - 1, ((px - M.l) / (W - M.l - M.r)) * (geom.n - 1)))
    const mi = Math.round(mif)
    setHoverMi(mi >= 0 && mi < geom.n ? mi : null)
    // nearest strand within 9 viewBox px of the cursor
    let best = -1, bestD = 9
    data.strands.forEach((st, i) => {
      const v = strandYAt(st, mif)
      if (v === null) return
      const d = Math.abs(geom.y(v) - py)
      if (d < bestD) { bestD = d; best = i }
    })
    setHoverStrand(best >= 0 ? best : null)
  }
  const activeStrand = pinned ?? hoverStrand

  const zeroY = geom.y(0)
  return (
    <figure className="m-0" ref={wrapRef}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none"
           role="img" aria-label="Cumulative return per dollar bid, by clearing-price bucket, across ERCOT monthly CRR auctions"
           onMouseMove={onMove}
           onMouseLeave={() => { setHoverMi(null); setHoverStrand(null) }}
           onClick={() => setPinned(p => (p !== null ? null : hoverStrand))}
           style={{ cursor: hoverStrand !== null ? 'pointer' : 'default' }}>
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
        <g fill="none" strokeWidth={0.8} clipPath="url(#flow-plot)">
          {data.strands.map((s, i) => (
            <path key={i} d={geom.strandLine(s.y)} stroke={RAMP[s.b]}
              strokeOpacity={activeStrand === null ? 0.035 : i === activeStrand ? 0 : 0.02} />
          ))}
        </g>
        {/* the strand under the cursor (or pinned by click), lifted out of the crowd */}
        {activeStrand !== null && data.strands[activeStrand] && (
          <g fill="none" clipPath="url(#flow-plot)" pointerEvents="none">
            <path d={geom.strandLine(data.strands[activeStrand].y)} stroke="#0b1216"
              strokeWidth={3.5} strokeOpacity={0.9} />
            <path d={geom.strandLine(data.strands[activeStrand].y)}
              stroke={RAMP[data.strands[activeStrand].b]} strokeWidth={1.8} strokeOpacity={0.95} />
          </g>
        )}

        {/* bucket aggregates: 2px, labeled */}
        <g fill="none" strokeWidth={2}>
          {data.buckets.map((b, bi) => (
            <path key={bi} d={geom.line(b.series)} stroke={RAMP[bi]}
              strokeLinecap="round"
              style={{ filter: 'drop-shadow(0 0 4px rgba(0,0,0,0.6))' }} />
          ))}
        </g>
        {!compact && labels.map(l => (
          <text key={l.bi} x={W - M.r + 8} y={l.yPos + 4} fontSize={11.5} fill="#dbe4e6">
            <tspan fill={RAMP[l.bi]}>●</tspan> {l.label}
            <tspan fill="#93a6ab"> {l.v >= 0 ? '+' : '−'}{Math.abs(l.v * 100).toFixed(0)}%</tspan>
          </text>
        ))}

        {/* x axis: sparse month ticks */}
        {data.months.map((m, mi) => (mi === geom.n - 1 || (mi % (compact ? 5 : 4) === 0 && geom.n - 1 - mi >= (compact ? 3 : 2))) && (
          <text key={m} x={geom.x(mi)} y={H - 12} textAnchor="middle" fontSize={10} fill="#61767e">
            {m}
          </text>
        ))}

        {/* strand readout: which path this line is, and where it stands */}
        {activeStrand !== null && data.strands[activeStrand] && hoverMi !== null && (() => {
          const st = data.strands[activeStrand]
          const v = st.y[hoverMi]
          const w = compact ? W - M.l - M.r : 340
          return (
            <g pointerEvents="none">
              <g transform={`translate(${compact ? M.l : Math.max(M.l, Math.min(geom.x(hoverMi) + 10, W - M.r - w - 4))}, ${M.t + 4})`}>
                <rect width={w} height={46} rx={5} fill="#1e3038" stroke="#2c424c" />
                <text x={8} y={16} fontSize={11} fill="#dbe4e6">
                  <tspan fill={RAMP[st.b]}>●</tspan> {st.l ?? 'path'}
                </text>
                <text x={8} y={33} fontSize={10.5} fill="#93a6ab">
                  usually clears ${(st.cp ?? 0).toFixed(2)} · {data.months[hoverMi]}:{' '}
                  {v !== null && v !== undefined
                    ? `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(0)}% per $1 paid in`
                    : 'not yet trading'}
                  {pinned !== null ? ' · click to unpin' : ' · click to pin'}
                </text>
              </g>
            </g>
          )
        })()}

        {/* hover crosshair + readout */}
        {hoverMi !== null && activeStrand === null && (
          <g pointerEvents="none">
            <line x1={geom.x(hoverMi)} x2={geom.x(hoverMi)} y1={M.t} y2={H - M.b}
              stroke="#93a6ab" strokeWidth={1} strokeDasharray="3 3" strokeOpacity={0.6} />
            {data.buckets.map((b, bi) => (
              <circle key={bi} cx={geom.x(hoverMi)} cy={geom.y(b.series[hoverMi])} r={3.5}
                fill={RAMP[bi]} stroke="#15242c" strokeWidth={2} />
            ))}
            <g transform={`translate(${Math.max(M.l, Math.min(geom.x(hoverMi) + 10, W - M.r - 168))}, ${M.t + 6})`}>
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
