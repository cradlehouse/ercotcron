'use client'
// My book: the signed-in holder's live positions, graded our way.
// Data: get_my_book() — scoped server-side to the caller's APPROVED claims.
import { Fragment, useEffect, useState } from 'react'
import { rpc } from '@/lib/rpc'
import { DailyChart, type DailyRow } from '../../daily-chart'
import { ProvenanceStrip } from '../../provenance-strip'



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
// Fractional holdings are real exposure: never round a nonzero MW to 0.
function fmtMw(v: number | string): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return '0'
  return Math.abs(n) < 10 ? n.toFixed(1).replace(/\.0$/, '') : Math.round(n).toLocaleString()
}

// Warnings arrive as raw diagnostics joined by ';' or '·', with one entry per
// constraint code ("1025__B: re-rated <90d; 6437__F: re-rated <90d"). Group
// the codes under one plain phrase; keep the raw text on hover.
const WARN_WORD: Record<string, string> = {
  're-rated <90d': 'constraint re-rated in the last 90 days',
}
function tidyWarnings(w: string): string[] {
  const byMsg = new Map<string, string[]>()
  const plain: string[] = []
  for (const part of w.split(/;\s*|\s·\s/).map(x => x.trim()).filter(Boolean)) {
    const m = part.match(/^([0-9A-Z_]+):\s*(.+)$/)
    if (m) byMsg.set(m[2], [...(byMsg.get(m[2]) ?? []), m[1]])
    else if (!plain.includes(part)) plain.push(part)
  }
  return [
    ...[...byMsg.entries()].map(([msg, codes]) => `${WARN_WORD[msg] ?? msg} (${[...new Set(codes)].join(', ')})`),
    ...plain.map(x => (x.length > 70 ? `${x.slice(0, 70)}…` : x)),
  ]
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
      const { data } = await rpc<DailyRow[]>('get_position_daily', {
        p_src: r.source, p_snk: r.sink, p_tou: r.tou, p_hedge: r.hedge,
      })
      setDaily(d => ({ ...d, [key]: data ?? [] }))
    }
  }

  useEffect(() => {
    // Session is guaranteed by the member layout's gate.
    ;(async () => {
      const { data: b, error } = await rpc<BookRow[]>('get_my_book')
      setRows(error ? [] : (b ?? []))
      const { data: rm } = await rpc<RunRow[]>('get_running_month')
      setRun(rm ?? [])
    })()
  }, [])

  if (rows === null)
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
  const totalPositions = rows.reduce((s, r) => s + Number(r.positions ?? 0), 0)

  return (
    <div className="mx-auto max-w-6xl p-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-[15px] font-semibold text-[#f2f6f6]">
          My book — {rows[0].holder_code}
        </h1>
        <span className="text-xs text-[#93a6ab]">
          {totalPositions.toLocaleString()} position{totalPositions === 1 ? '' : 's'} across {rows.length} path{rows.length === 1 ? '' : 's'} · {fmtMw(totalMw)} MW live
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
                        {r.source} → {r.sink}
                        <a className="ml-2 text-[#eda63a] hover:text-[#f5b95c]" title="open this path's dossier"
                           onClick={e => e.stopPropagation()}
                           href={`/path?src=${encodeURIComponent(r.source)}&snk=${encodeURIComponent(r.sink)}`}>↗</a>
                      </td>
                      <td className="px-2 py-1.5 text-[#93a6ab]">{r.tou} · {r.hedge}</td>
                      <td className="px-2 py-1.5 text-right font-mono">{fmtMw(r.mw)}</td>
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
                                  <DailyChart rows={dd} path={{ source: r.source, sink: r.sink, tou: r.tou, hedge: r.hedge, mw: Number(r.mw) }} />
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
                <td className="px-2 py-1.5 text-right font-mono">{fmtMw(r.mw)}</td>
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
                  {r.warnings ? (
                    <span className="ml-1 text-[10px] text-[#61767e]" title={r.warnings}>
                      ({(() => { const w = tidyWarnings(r.warnings); return w.length > 2 ? `${w.slice(0, 2).join('; ')} +${w.length - 2} more` : w.join('; ') })()})
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ProvenanceStrip />
    </div>
  )
}
