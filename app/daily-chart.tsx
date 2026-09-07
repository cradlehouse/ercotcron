'use client'
// Shared daily win/loss chart: bars on settled days (net = paid out − cost),
// the rest of the delivery month laid out empty, cumulative net line on top.
// Used by My book's running positions and the method progress screen.
//
// With a `path` prop, a settled day's bar is clickable and stretches into
// that day's 24 DAM hours, bunched into the TOU blocks you can actually buy
// (Off-peak HE1-6 · Peak HE7-22 · Off-peak HE23-24). Hours outside the
// position's own block are shown dimmed — the path moved, but this position
// doesn't collect those hours. CRRs settle on DAM hourly prices, so hourly
// is the finest honest grain (there is no 15-minute settlement here).
import { useState } from 'react'
import { sb } from '@/lib/supabase'

export type DailyRow = { d: string; hours: number; paid_in: number; paid_out: number }
export type PathId = { source: string; sink: string; tou: string; hedge: string; mw: number }

type HourRow = { he: number; block: string; collects: boolean; paid_per_mwh: number }

function DayHours({ day, hours, mw, tou }: { day: string; hours: HourRow[]; mw: number; tou: string }) {
  const paid = (h: HourRow) => h.paid_per_mwh * mw
  const maxAbs = Math.max(...hours.map(h => Math.abs(paid(h))), 1)
  const collected = hours.filter(h => h.collects).reduce((a, h) => a + paid(h), 0)
  const W = 720, H = 120, M = { t: 16, b: 30, l: 8, r: 64 }
  const bw = (W - M.l - M.r) / 24
  const y = (v: number) => M.t + (1 - (v + maxAbs) / (2 * maxAbs)) * (H - M.t - M.b)
  const zero = y(0)
  // block boundaries after HE6 and HE22 (bars are 0-indexed by he-1)
  const bx = (he: number) => M.l + (he - 1) * bw
  return (
    <div className="mt-1 rounded border border-line/60 bg-ink/40 p-2">
      <div className="mb-1 flex items-baseline gap-3 text-[11.5px]">
        <span className="text-[#dbe4e6]">{day}, hour by hour</span>
        <span className={collected >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {collected >= 0 ? '+' : '−'}${Math.abs(Math.round(collected)).toLocaleString()} collected in your block
        </span>
        <span className="text-[#61767e]">dimmed hours = outside {tou}, not collected</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none" role="img"
           aria-label={`Hourly payout on ${day}, grouped into TOU blocks`}>
        <line x1={M.l} x2={W - M.r} y1={zero} y2={zero} stroke="#3a4f58" strokeWidth={1} />
        {[6, 22].map(he => (
          <line key={he} x1={bx(he + 1) - 1} x2={bx(he + 1) - 1} y1={M.t - 4} y2={H - M.b + 4}
                stroke="#3a4f58" strokeWidth={1} strokeDasharray="2 3" />
        ))}
        {hours.map(h => {
          const v = paid(h)
          const yTop = v >= 0 ? y(v) : zero
          const bh = Math.max(Math.abs(zero - y(v)), 1)
          return (
            <rect key={h.he} x={bx(h.he) + 1} y={yTop} width={Math.max(bw - 2, 2)} height={bh} rx={1}
              fill={v >= 0 ? '#34d399' : '#f87171'} fillOpacity={h.collects ? 0.9 : 0.18}>
              <title>{`HE${h.he} (${h.block}${h.collects ? '' : ' — not collected'}): ${v >= 0 ? '+' : '−'}$${Math.abs(v).toFixed(0)}`}</title>
            </rect>
          )
        })}
        {[['Off-peak', 3.5], ['Peak (HE7–22)', 14.5], ['Off-pk', 23.5]].map(([label, mid]) => (
          <text key={label as string} x={M.l + (mid as number) * bw} y={H - 8} textAnchor="middle"
                fontSize={10.5} fill="#61767e">{label}</text>
        ))}
        {[1, 7, 22, 24].map(he => (
          <text key={he} x={bx(he) + bw / 2} y={M.t - 5} textAnchor="middle" fontSize={9} fill="#4a5d64">{he}</text>
        ))}
      </svg>
    </div>
  )
}

export function DailyChart({ rows, month, path }: { rows: DailyRow[]; month?: string; path?: PathId }) {
  const [openDay, setOpenDay] = useState<string | null>(null)
  const [dayHours, setDayHours] = useState<Record<string, HourRow[] | 'loading'>>({})

  async function toggleDay(d: string) {
    if (!path) return
    if (openDay === d) { setOpenDay(null); return }
    setOpenDay(d)
    if (!dayHours[d]) {
      setDayHours(h => ({ ...h, [d]: 'loading' }))
      const { data } = await sb.rpc('get_path_day', {
        p_src: path.source, p_snk: path.sink, p_tou: path.tou, p_hedge: path.hedge, p_day: d,
      })
      setDayHours(h => ({ ...h, [d]: ((data as { hours?: HourRow[] } | null)?.hours ?? []) }))
    }
  }

  const ref = month ? new Date(`${month}-15T00:00:00`) : new Date()
  const daysInMonth = new Date(ref.getFullYear(), ref.getMonth() + 1, 0).getDate()
  const byDay = new Map(rows.map(r => [Number(r.d.slice(8, 10)), r]))
  const nets = rows.map(r => r.paid_out - r.paid_in)
  const maxAbs = Math.max(...nets.map(Math.abs), 1)
  let cum = 0
  const cums: (number | null)[] = []
  for (let day = 1; day <= daysInMonth; day++) {
    const r = byDay.get(day)
    if (r) { cum += r.paid_out - r.paid_in; cums.push(cum) } else cums.push(byDay.size && day <= Number(rows[rows.length - 1]?.d.slice(8, 10)) ? cum : null)
  }
  const cumMax = Math.max(...cums.filter((c): c is number => c !== null).map(Math.abs), maxAbs)
  const W = 720, H = 150, M = { t: 10, b: 22, l: 8, r: 64 }
  const bw = (W - M.l - M.r) / daysInMonth
  const y = (v: number) => M.t + (1 - (v + cumMax) / (2 * cumMax)) * (H - M.t - M.b)
  const zero = y(0)
  let cumPath = ''
  cums.forEach((c, i) => {
    if (c === null) return
    const x = M.l + (i + 0.5) * bw
    cumPath += (cumPath ? 'L' : 'M') + x.toFixed(1) + ',' + y(c).toFixed(1)
  })
  const lastCum = [...cums].reverse().find(c => c !== null) ?? 0
  const openRows = openDay ? dayHours[openDay] : null
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none" role="img"
           aria-label="Daily net payout for this position across the delivery month">
        <line x1={M.l} x2={W - M.r} y1={zero} y2={zero} stroke="#3a4f58" strokeWidth={1} />
        {Array.from({ length: daysInMonth }, (_, i) => {
          const day = i + 1
          const r = byDay.get(day)
          const x = M.l + i * bw + 1
          if (!r) {
            return <line key={day} x1={x + bw / 2 - 1} x2={x + bw / 2 - 1} y1={zero - 1} y2={zero + 1} stroke="#2c424c" strokeWidth={1.5} />
          }
          const net = r.paid_out - r.paid_in
          const yTop = net >= 0 ? y(net) : zero
          const h = Math.max(Math.abs(zero - y(net)), 1.5)
          const sel = openDay === r.d
          return (
            <g key={day} onClick={() => toggleDay(r.d)} style={path ? { cursor: 'pointer' } : undefined}>
              <rect x={x} y={yTop} width={Math.max(bw - 2, 2)} height={h} rx={1.5}
                fill={net >= 0 ? '#34d399' : '#f87171'} fillOpacity={sel ? 1 : 0.85}
                stroke={sel ? '#f2f6f6' : 'none'} strokeWidth={sel ? 1 : 0}>
                <title>{`${r.d}: paid out $${r.paid_out.toLocaleString()} vs $${r.paid_in.toLocaleString()} in — net ${net >= 0 ? '+' : '−'}$${Math.abs(net).toLocaleString()}${path ? ' · click for the hours' : ''}`}</title>
              </rect>
            </g>
          )
        })}
        <path d={cumPath} fill="none" stroke="#93a6ab" strokeWidth={1.5} strokeDasharray="4 3" />
        <text x={W - M.r + 6} y={y(lastCum) + 4} fontSize={12} fill={lastCum >= 0 ? '#34d399' : '#f87171'}>
          {lastCum >= 0 ? '+' : '−'}${Math.abs(lastCum).toLocaleString()} net
        </text>
        {[1, 10, 20, daysInMonth].map(d => (
          <text key={d} x={M.l + (d - 0.5) * bw} y={H - 6} textAnchor="middle" fontSize={11} fill="#61767e">{d}</text>
        ))}
      </svg>
      {openDay && path && (
        openRows === 'loading' || !openRows
          ? <div className="mt-1 text-[11.5px] text-[#7d9096]">pulling the hours…</div>
          : <DayHours day={openDay} hours={openRows} mw={path.mw} tou={path.tou} />
      )}
    </div>
  )
}
