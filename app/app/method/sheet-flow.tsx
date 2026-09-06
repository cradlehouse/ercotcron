'use client'
// The sheet's month as a flow field: every traded recommendation a strand
// (cumulative return per $1 at its clearing price, day by day), three hero
// lines carrying the fight — our fills, the market's buys at prices we
// refused, and the red don't-bids. Same construction as the landing chart,
// but the x-axis is the days of one delivery month.
import { useEffect, useRef, useState } from 'react'
import { sb } from '@/lib/supabase'
import { DailyChart } from '../../daily-chart'

type FlowRow = {
  source: string; sink: string; tou: string; hedge: string
  tier: string; filled: boolean; cp: number; mw: number
  days: { d: number; hrs: number; ppm: number }[]
}
type Flow = { month: string; rows: FlowRow[] }

const CLASSES = [
  { key: 'ours', label: 'our fills', color: '#34d399' },
  { key: 'market', label: "the market's buys at prices we refused", color: '#f87171' },
  { key: 'reds', label: "red don't-bids (traded)", color: '#c07b5a' },
] as const
export type ClassKey = typeof CLASSES[number]['key']

function classOf(r: FlowRow): ClassKey {
  if (r.tier === 'red') return 'reds'
  return r.filled ? 'ours' : 'market'
}

export function SheetFlowChart({ sheet, camp }: { sheet: string; camp?: ClassKey | null }) {
  const [data, setData] = useState<Flow | null>(null)
  const [hover, setHover] = useState<{ i: number; day: number } | null>(null)
  const [pinned, setPinned] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [boxW, setBoxW] = useState(920)

  useEffect(() => {
    sb.rpc('get_sheet_flow', { p_sheet: sheet }).then(({ data: d }) => d && setData(d as Flow))
  }, [sheet])
  useEffect(() => {
    if (!wrapRef.current) return
    const ro = new ResizeObserver(([e]) => setBoxW(e.contentRect.width))
    ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [data])

  if (!data || data.rows.length === 0) return null

  const ref = new Date(`${data.month}-15T00:00:00`)
  const daysInMonth = new Date(ref.getFullYear(), ref.getMonth() + 1, 0).getDate()
  const W = Math.max(360, Math.round(boxW || 920))
  const compact = W < 700
  const H = 380
  const M = { t: 16, r: compact ? 14 : 250, b: 28, l: 52 }

  // per-row cumulative return series (return per $1 at its clearing)
  const series = data.rows.map(r => {
    let paid = 0, cost = 0
    const ys: (number | null)[] = []
    const byDay = new Map(r.days.map(d => [d.d, d]))
    for (let day = 1; day <= daysInMonth; day++) {
      const d = byDay.get(day)
      if (d) { paid += d.ppm * r.mw; cost += r.cp * d.hrs * r.mw }
      ys.push(cost > 0 ? paid / cost - 1 : null)
    }
    return { r, ys, cls: classOf(r) }
  })
  // hero lines: aggregate per class
  const heroes = CLASSES.map(c => {
    const members = series.filter(s => s.cls === c.key)
    let ys: (number | null)[] = []
    for (let day = 0; day < daysInMonth; day++) {
      let paid = 0, cost = 0, any = false
      for (const s of members) {
        const r = s.r
        const byDay = new Map(r.days.map(d => [d.d, d]))
        for (let dd = 1; dd <= day + 1; dd++) {
          const d = byDay.get(dd)
          if (d) { paid += d.ppm * r.mw; cost += r.cp * d.hrs * r.mw; any = true }
        }
      }
      ys.push(any && cost > 0 ? paid / cost - 1 : null)
    }
    return { ...c, ys, n: members.length }
  })

  const heroVals = heroes.flatMap(h => h.ys.filter((v): v is number => v !== null))
  const yMin = Math.max(Math.min(...heroVals, -0.4) - 0.15, -1)
  const yMax = Math.min(Math.max(...heroVals, 0.4) + 0.15, 3)
  const x = (day: number) => M.l + ((day - 1) / (daysInMonth - 1)) * (W - M.l - M.r)
  const y = (v: number) => M.t + (1 - (Math.max(yMin, Math.min(yMax, v)) - yMin) / (yMax - yMin)) * (H - M.t - M.b)
  const line = (ys: (number | null)[], band = false) => {
    let d = ''; let pen = false
    ys.forEach((v, i) => {
      if (v === null || (band && (v < yMin - 0.02 || v > yMax + 0.02))) { pen = false; return }
      d += (pen ? 'L' : 'M') + x(i + 1).toFixed(1) + ',' + y(v).toFixed(1)
      pen = true
    })
    return d
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const px = ((e.clientX - rect.left) / rect.width) * W
    const py = ((e.clientY - rect.top) / rect.height) * H
    const day = Math.max(1, Math.min(daysInMonth, Math.round(((px - M.l) / (W - M.l - M.r)) * (daysInMonth - 1)) + 1))
    let best = -1, bestD = 10
    series.forEach((s, i) => {
      const v = s.ys[day - 1]
      if (v === null) return
      const d = Math.abs(y(v) - py)
      if (d < bestD) { bestD = d; best = i }
    })
    setHover(best >= 0 ? { i: best, day } : null)
  }

  const zero = y(0)
  return (
    <div ref={wrapRef} className="mt-3">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none"
           role="img" aria-label="Daily cumulative return per dollar for every traded recommendation on this sheet"
           onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           onClick={() => setPinned(p => (p !== null ? null : hover?.i ?? null))}
           style={{ cursor: hover ? 'pointer' : 'default' }}>
        {[-0.5, 0.5, 1, 1.5, 2].filter(v => v > yMin && v < yMax).map(v => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} stroke="#22333c" strokeWidth={1} />
            <text x={M.l - 6} y={y(v) + 4} textAnchor="end" fontSize={12} fill="#61767e">
              {v > 0 ? `+${Math.round(v * 100)}%` : `−${Math.round(-v * 100)}%`}
            </text>
          </g>
        ))}
        <line x1={M.l} x2={W - M.r} y1={zero} y2={zero} stroke="#3a4f58" strokeWidth={1.5} />
        <text x={M.l - 6} y={zero + 4} textAnchor="end" fontSize={12} fill="#93a6ab">0%</text>

        <g fill="none" strokeWidth={1}>
          {series.map((s, i) => (
            <path key={i} d={line(s.ys, true)}
              stroke={CLASSES.find(c => c.key === s.cls)!.color}
              strokeOpacity={camp && s.cls !== camp ? 0.03 : hover ? (hover.i === i ? 0 : 0.08) : 0.14} />
          ))}
        </g>
        <g fill="none" strokeWidth={2.5} strokeOpacity={hover ? 0.35 : 1}>
          {heroes.filter(h => !camp || h.key === camp).map(h => (
            <path key={h.key} d={line(h.ys)} stroke={h.color} strokeLinecap="round"
              style={{ filter: 'drop-shadow(0 0 4px rgba(0,0,0,0.6))' }} />
          ))}
        </g>
        {hover && (() => {
          const s = series[hover.i]
          const v = s.ys[hover.day - 1]
          return (
            <g pointerEvents="none">
              <path d={line(s.ys, true)} fill="none"
                stroke={CLASSES.find(c => c.key === s.cls)!.color} strokeWidth={2} />
              <g transform={`translate(${Math.max(M.l, Math.min(x(hover.day) + 10, W - M.r - 330))}, ${M.t + 4})`}>
                <rect width={320} height={40} rx={5} fill="#1e3038" stroke="#2c424c" />
                <text x={8} y={17} fontSize={13} fill="#dbe4e6">
                  <tspan fill={CLASSES.find(c => c.key === s.cls)!.color}>●</tspan>{' '}
                  {s.r.source} → {s.r.sink} · {s.r.tou} · {s.r.hedge}
                </text>
                <text x={8} y={33} fontSize={12} fill="#93a6ab">
                  {CLASSES.find(c => c.key === s.cls)!.label} · cleared ${Number(s.r.cp).toFixed(2)} · day {hover.day}:{' '}
                  {v !== null ? `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(0)}% per $1` : '—'}
                </text>
              </g>
            </g>
          )
        })()}
        {!compact && (() => {
          const ends = heroes
            .map(h => ({ h, v: [...h.ys].reverse().find(v => v !== null) ?? null }))
            .filter(e => e.v !== null)
            .map(e => ({ ...e, yy: y(e.v!) }))
            .sort((a, b) => a.yy - b.yy)
          for (let i = 1; i < ends.length; i++) {
            if (ends[i].yy - ends[i - 1].yy < 19) ends[i].yy = ends[i - 1].yy + 19
          }
          return ends.map(e => (
            <text key={e.h.key} x={W - M.r + 8} y={e.yy + 4} fontSize={13} fill="#dbe4e6">
              <tspan fill={e.h.color}>●</tspan> {e.h.label} ({e.h.n}){' '}
              <tspan fill="#93a6ab">{e.v! >= 0 ? '+' : '−'}{Math.abs(e.v! * 100).toFixed(0)}%</tspan>
            </text>
          ))
        })()}
        {[1, 5, 10, 15, 20, 25, daysInMonth].map(d => (
          <text key={d} x={x(d)} y={H - 8} textAnchor="middle" fontSize={12} fill="#61767e">{d}</text>
        ))}
      </svg>
      <p className="mt-1 text-[12px] text-[#61767e]">
        Each strand: one traded recommendation&apos;s cumulative return per $1 at its clearing
        price, day by day through {data.month}. Heavy lines are the three camps. Hover a strand
        to identify it; click to pin its daily over/under below. Hypothetical — no positions held.
      </p>
      {camp && (() => {
        const members = series.filter(s => s.cls === camp)
        const agg = new Map<number, { hrs: number; paid_in: number; paid_out: number }>()
        for (const s of members) {
          for (const d of s.r.days) {
            const a = agg.get(d.d) ?? { hrs: 0, paid_in: 0, paid_out: 0 }
            a.hrs += d.hrs
            a.paid_in += s.r.cp * d.hrs * s.r.mw
            a.paid_out += d.ppm * s.r.mw
            agg.set(d.d, a)
          }
        }
        const rows = [...agg.entries()].sort((a, b) => a[0] - b[0]).map(([d, a]) => ({
          d: `${data.month}-${String(d).padStart(2, '0')}`,
          hours: a.hrs, paid_in: Math.round(a.paid_in), paid_out: Math.round(a.paid_out),
        }))
        if (rows.length === 0) return null
        return (
          <div className="mt-3 rounded border border-line bg-panel/50 p-3">
            <div className="text-[13px] text-[#dbe4e6]">
              {CLASSES.find(c => c.key === camp)!.label} — the whole group&apos;s daily over/under
            </div>
            <div className="mt-2"><DailyChart rows={rows} month={data.month} /></div>
          </div>
        )
      })()}
      {pinned !== null && series[pinned] && (() => {
        const s = series[pinned]
        const rows = s.r.days.map(d => ({
          d: `${data.month}-${String(d.d).padStart(2, '0')}`,
          hours: d.hrs,
          paid_in: Math.round(s.r.cp * d.hrs * s.r.mw),
          paid_out: Math.round(d.ppm * s.r.mw),
        }))
        return (
          <div className="mt-3 rounded border border-line bg-panel/50 p-3">
            <div className="flex items-baseline gap-3 text-[13px]">
              <span className="font-mono text-[#dbe4e6]">{s.r.source} → {s.r.sink} · {s.r.tou} · {s.r.hedge}</span>
              <span className="text-[11.5px] text-[#7d9096]">
                {CLASSES.find(c => c.key === s.cls)!.label} · daily over/under at ${Number(s.r.cp).toFixed(2)} clearing
              </span>
              <button onClick={() => setPinned(null)} className="ml-auto text-[11.5px] text-[#7d9096] hover:text-[#dbe4e6]">close ×</button>
            </div>
            <div className="mt-2"><DailyChart rows={rows} month={data.month} /></div>
          </div>
        )
      })()}
    </div>
  )
}
