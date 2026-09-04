'use client'
// My book: the signed-in holder's live positions, graded our way.
// Data: get_my_book() — scoped server-side to the caller's APPROVED claims.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

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
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      setAuthed(true)
      const { data: b, error } = await sb.rpc('get_my_book')
      setRows(error ? [] : ((b as BookRow[]) ?? []))
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
