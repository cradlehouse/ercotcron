'use client'
// My book: the signed-in holder's live positions, graded our way.
// Data: get_my_book() — scoped server-side to the caller's APPROVED claims.
import { Fragment, useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

type DailyRow = { d: string; hours: number; paid_in: number; paid_out: number }

// Daily win/loss for one position, covering the WHOLE delivery month: bars on
// settled days (net = paid out − pro-rata cost), the rest of the month laid
// out empty so the remaining runway is visible. Cumulative net line on top.
function DailyChart({ rows }: { rows: DailyRow[] }) {
  const now = new Date()
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
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
  return (
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
        return (
          <g key={day}>
            <rect x={x} y={yTop} width={Math.max(bw - 2, 2)} height={h} rx={1.5}
              fill={net >= 0 ? '#34d399' : '#f87171'} fillOpacity={0.85}>
              <title>{`${r.d}: paid out $${r.paid_out.toLocaleString()} vs $${r.paid_in.toLocaleString()} in — net ${net >= 0 ? '+' : '−'}$${Math.abs(net).toLocaleString()}`}</title>
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
  )
}

type RunRow = {
  source: string; sink: string; tou: string; hedge: string
  mw: number; cp: number; hours: number; paid_in: number; paid_out: number
}
type BookRow = {
  holder_code: string; source: string; sink: string; time_of_use: string
  hedge_type: string; mw: number; positions: number
  first_start: string; last_end: string; avg_clear: number | null
  tier: string; margin_x: number | null; warnings: string | null
}

const TIER_STYLE: Record<string, string> = {
  good: 'text-emerald-400', flagged: 'text-amber-400',
  thin: 'text-[#93a6ab]', unscored: 'text-[#61767e]',
}
const TIER_WORD: Record<string, string> = {
  good: 'holds up', flagged: 'flagged', thin: 'thin margin', unscored: 'not scored',
}

export default function MyBook() {
  const [rows, setRows] = useState<BookRow[] | null>(null)
  const [run, setRun] = useState<RunRow[]>([])
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [daily, setDaily] = useState<Record<string, DailyRow[] | 'loading'>>({})

  async function toggleDaily(r: RunRow) {
    const key = `${r.source}|${r.sink}|${r.tou}|${r.hedge}`
    if (openKey === key) { setOpenKey(null); return }
    setOpenKey(key)
    if (!daily[key]) {
      setDaily(d => ({ ...d, [key]: 'loading' }))
      const { data } = await sb.rpc('get_position_daily', {
        p_src: r.source, p_snk: r.sink, p_tou: r.tou, p_hedge: r.hedge,
      })
      setDaily(d => ({ ...d, [key]: (data as DailyRow[]) ?? [] }))
    }
  }
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      setAuthed(true)
      const { data: b, error } = await sb.rpc('get_my_book')
      setRows(error ? [] : ((b as BookRow[]) ?? []))
      const { data: rm } = await sb.rpc('get_running_month')
      setRun((rm as RunRow[]) ?? [])
    })
  }, [])

  if (authed === null || rows === null)
    return <div className="p-6 text-sm text-[#93a6ab]">loading your book…</div>

  if (rows.length === 0)
    return (
      <div className="mx-auto max-w-2xl p-8">
        <h1 className="text-lg font-medium text-[#f2f6f6]">My book</h1>
        <p className="mt-3 text-sm leading-relaxed text-[#93a6ab]">
          No positions to show yet. Either your CRR account claim is still pending
          verification, or you haven&apos;t claimed a code — do that on the{' '}
          <a href="/app" className="text-[#eda63a] hover:underline">Today page</a>.
          Once approved, every live position appears here graded against the
          current scan: what holds up, what&apos;s running thin, and what sits on a
          constraint that changed.
        </p>
      </div>
    )

  const totalMw = rows.reduce((s, r) => s + Number(r.mw), 0)
  const flagged = rows.filter(r => r.tier === 'flagged')

  return (
    <div className="mx-auto max-w-6xl p-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[15px] font-semibold text-[#f2f6f6]">
          My book — {rows[0].holder_code}
        </h1>
        <span className="text-xs text-[#93a6ab]">
          {rows.length} paths · {Math.round(totalMw).toLocaleString()} MW live
        </span>
        {flagged.length > 0 && (
          <span className="text-xs text-amber-400">
            {flagged.length} paths flagged — a driving constraint changed or a caution applies
          </span>
        )}
      </div>
      <p className="mb-3 mt-1 max-w-[90ch] text-[12px] text-[#7d9096]">
        Every live position, graded against the latest valuation run. &ldquo;Holds up&rdquo;
        = worth more than its recent clearing price on real history. Grades are
        our read of public data — your sizing and your exits stay your call.
      </p>
      {run.length > 0 && (
        <div className="mb-5">
          <div className="flex items-baseline gap-3">
            <h2 className="text-[14px] font-semibold text-[#f2f6f6]">This month, running</h2>
            <span className="text-[11.5px] text-[#61767e]">
              settled days so far — partial-month description, not the official score (that
              waits for the complete month)
            </span>
          </div>
          <div className="mt-2 overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full min-w-[760px] border-collapse text-[12px]">
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
                  <th className="w-7 px-2 py-2"></th>
                  <th className="px-2 py-2">Path</th>
                  <th className="px-2 py-2">Block · type</th>
                  <th className="px-2 py-2 text-right">MW</th>
                  <th className="px-2 py-2 text-right">Hours banked</th>
                  <th className="px-2 py-2 text-right">Paid in (pro-rata)</th>
                  <th className="px-2 py-2 text-right">Paid out</th>
                  <th className="px-2 py-2 text-right">Pace</th>
                </tr>
              </thead>
              <tbody>
                {run.map((r, i) => {
                  const pace = r.paid_in > 0 ? Math.round((r.paid_out / r.paid_in) * 100) : null
                  const key = `${r.source}|${r.sink}|${r.tou}|${r.hedge}`
                  const open = openKey === key
                  const dd = daily[key]
                  return (
                    <Fragment key={key}><tr onClick={() => toggleDaily(r)}
                        className={`cursor-pointer border-b border-line/50 last:border-0 hover:bg-panel-2/40 ${open ? 'bg-panel-2/30' : ''}`}
                        title="click for the daily win/loss picture">
                      <td className="px-2 py-1.5 text-[11px] text-[#eda63a]">{open ? '▾' : '▸'}</td>
                      <td className="px-2 py-1.5 font-mono text-[11.5px]">
                        <a className="hover:text-white" onClick={e => e.stopPropagation()}
                           href={`/path?src=${encodeURIComponent(r.source)}&snk=${encodeURIComponent(r.sink)}`}>
                          {r.source} → {r.sink}
                        </a>
                      </td>
                      <td className="px-2 py-1.5 text-[#93a6ab]">{r.tou} · {r.hedge}</td>
                      <td className="px-2 py-1.5 text-right font-mono">{Math.round(Number(r.mw))}</td>
                      <td className="px-2 py-1.5 text-right font-mono">{r.hours}</td>
                      <td className="px-2 py-1.5 text-right font-mono">${Number(r.paid_in).toLocaleString()}</td>
                      <td className="px-2 py-1.5 text-right font-mono">${Number(r.paid_out).toLocaleString()}</td>
                      <td className={`px-2 py-1.5 text-right font-mono ${pace === null ? 'text-[#61767e]' : pace >= 100 ? 'text-emerald-400' : pace >= 50 ? 'text-[#93a6ab]' : 'text-amber-400'}`}>
                        {pace === null ? '—' : `${pace}%`}
                      </td>
                    </tr>
                    {open && (
                      <tr className="border-b border-line/50">
                        <td colSpan={8} className="bg-ink/40 px-3 py-3">
                          {dd === 'loading' || !dd
                            ? <div className="text-[12px] text-[#7d9096]">pulling the daily record…</div>
                            : dd.length === 0
                              ? <div className="text-[12px] text-[#93a6ab]">No settled days yet this month for this block.</div>
                              : <>
                                  <DailyChart rows={dd} />
                                  <div className="mt-1 text-[11px] text-[#61767e]">
                                    Green bars = days that paid more than their pro-rata cost; red = days that didn&apos;t.
                                    Dashes mark the month&apos;s remaining days; dotted line is cumulative net.
                                  </div>
                                </>}
                        </td>
                      </tr>
                    )}</Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-[#61767e]">
            Pace = paid out over pro-rata cost of the hours banked so far. Options can never
            lose more than their premium; spike paths are expected to run cold between payoffs.
          </p>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full min-w-[900px] border-collapse text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
              <th className="px-2 py-2">Path</th>
              <th className="px-2 py-2">TOU · hedge</th>
              <th className="px-2 py-2 text-right">MW</th>
              <th className="px-2 py-2 text-right">Positions</th>
              <th className="px-2 py-2">Delivery</th>
              <th className="px-2 py-2 text-right">Avg clear</th>
              <th className="px-2 py-2 text-right">Margin</th>
              <th className="px-2 py-2">Our read</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-line/50 hover:bg-panel-2/40">
                <td className="px-2 py-1.5 font-mono text-[11.5px]">{r.source} → {r.sink}</td>
                <td className="px-2 py-1.5 text-[#93a6ab]">{r.time_of_use} · {r.hedge_type}</td>
                <td className="px-2 py-1.5 text-right font-mono">{Math.round(Number(r.mw))}</td>
                <td className="px-2 py-1.5 text-right text-[#93a6ab]">{r.positions}</td>
                <td className="px-2 py-1.5 text-[#93a6ab]">
                  {r.first_start?.slice(0, 7)} → {r.last_end?.slice(0, 7)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {r.avg_clear !== null ? `$${Number(r.avg_clear).toFixed(2)}` : '—'}
                </td>
                <td className="px-2 py-1.5 text-right font-mono">
                  {r.margin_x !== null ? `${Number(r.margin_x).toFixed(2)}×` : '—'}
                </td>
                <td className={`px-2 py-1.5 ${TIER_STYLE[r.tier] ?? ''}`}>
                  {TIER_WORD[r.tier] ?? r.tier}
                  {r.warnings ? <span className="ml-1 text-[10px] text-[#61767e]">({r.warnings.slice(0, 60)})</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
