'use client'
// The method scored against itself, visible to every member — every
// snapshotted sheet row's counterfactual (would the reference limit have
// filled; what delivery paid), including the red don't-bid calls. This IS
// the self-scoring methodology §10 pre-registers.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

type SheetAgg = { sheet: string; tier: string; rows: number; snapshot_at: string; filled: number | null; cost: number | null; realized: number | null; pnl: number | null }
type Row = { sheet: string; source: string; sink: string; time_of_use: string; hedge_type: string; tier: string; ref_limit: number | null; suggested_mw: number | null; clearing: number | null; filled: boolean | null; cost: number | null; realized: number | null; pnl: number | null }
type Score = { sheets: SheetAgg[]; rows: Row[] }

const usd = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${Number(v).toLocaleString()}`)
const TIER_COLOR: Record<string, string> = { green: 'text-emerald-400', amber: 'text-amber-400', red: 'text-red-400' }

export default function MethodScore() {
  const [score, setScore] = useState<Score | null>(null)
  const [state, setState] = useState<'loading' | 'denied' | 'ok'>('loading')

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      const { data: s, error } = await sb.rpc('get_method_score')
      if (error || !s) { setState('denied'); return }
      setScore(s as Score)
      setState('ok')
    })
  }, [])

  if (state === 'loading') return <div className="p-6 text-sm text-[#7d9096]">loading…</div>
  if (state === 'denied') return <div className="p-6 text-sm text-[#93a6ab]">Couldn&apos;t load the method score — refresh, or sign in again.</div>

  return (
    <div className="mx-auto max-w-6xl p-4 text-[#f2f6f6]">
      <h1 className="text-[15px] font-semibold">Method score — every sheet, every row, counterfactual</h1>
      <p className="mt-1 max-w-[95ch] text-[12.5px] text-[#7d9096]">
        Sheets are snapshotted at publish (immutable) and scored as results and settlement
        arrive: filled = the reference limit met the clearing price; cost, realized, and P&L at
        the sheet&apos;s own suggested size. Red rows are scored per-MW — they grade the
        don&apos;t-bid calls. Favorable and unfavorable alike, never edited.
        HYPOTHETICAL PERFORMANCE DISCLOSURE: no actual bids were submitted and no positions
        held; hypothetical results do not reflect actual market participation, and no
        representation is made that any account will achieve similar results.
      </p>

      <h2 className="mt-6 text-[14px] font-medium">By sheet and tier</h2>
      <div className="mt-2 overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full min-w-[720px] border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
              <th className="px-2 py-2">Sheet</th><th className="px-2 py-2">Tier</th>
              <th className="px-2 py-2 text-right">Rows</th><th className="px-2 py-2 text-right">Would have filled</th>
              <th className="px-2 py-2 text-right">Cost</th><th className="px-2 py-2 text-right">Realized</th>
              <th className="px-2 py-2 text-right">P&L</th><th className="px-2 py-2">Snapshot</th>
            </tr>
          </thead>
          <tbody>
            {(score?.sheets ?? []).map((s, i) => (
              <tr key={i} className="border-b border-line/50 last:border-0">
                <td className="px-2 py-1.5">{s.sheet}</td>
                <td className={`px-2 py-1.5 ${TIER_COLOR[s.tier] ?? ''}`}>{s.tier}</td>
                <td className="px-2 py-1.5 text-right tnum">{s.rows}</td>
                <td className="px-2 py-1.5 text-right tnum">{s.filled ?? '—'}</td>
                <td className="px-2 py-1.5 text-right tnum">{usd(s.cost)}</td>
                <td className="px-2 py-1.5 text-right tnum">{usd(s.realized)}</td>
                <td className={`px-2 py-1.5 text-right tnum ${(s.pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{usd(s.pnl)}</td>
                <td className="px-2 py-1.5 text-[#61767e]">{s.snapshot_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mt-6 text-[14px] font-medium">Rows</h2>
      <div className="mt-2 overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full min-w-[900px] border-collapse text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
              <th className="px-2 py-2">Sheet</th><th className="px-2 py-2">Path</th>
              <th className="px-2 py-2">Block · type</th><th className="px-2 py-2">Tier</th>
              <th className="px-2 py-2 text-right">Ref limit</th><th className="px-2 py-2 text-right">MW</th>
              <th className="px-2 py-2 text-right">Cleared</th><th className="px-2 py-2 text-right">Filled?</th>
              <th className="px-2 py-2 text-right">Cost</th><th className="px-2 py-2 text-right">Realized</th>
              <th className="px-2 py-2 text-right">P&L</th>
            </tr>
          </thead>
          <tbody>
            {(score?.rows ?? []).map((r, i) => (
              <tr key={i} className="border-b border-line/50 last:border-0 text-[#93a6ab]">
                <td className="px-2 py-1.5">{r.sheet}</td>
                <td className="px-2 py-1.5 font-mono text-[11px] text-[#dbe4e6]">
                  <a className="hover:text-white" href={`/path?src=${encodeURIComponent(r.source)}&snk=${encodeURIComponent(r.sink)}`}>
                    {r.source} → {r.sink}
                  </a>
                </td>
                <td className="px-2 py-1.5">{r.time_of_use} · {r.hedge_type}</td>
                <td className={`px-2 py-1.5 ${TIER_COLOR[r.tier] ?? ''}`}>{r.tier}</td>
                <td className="px-2 py-1.5 text-right tnum">{r.ref_limit !== null ? `$${Number(r.ref_limit).toFixed(2)}` : '—'}</td>
                <td className="px-2 py-1.5 text-right tnum">{r.suggested_mw ?? '—'}</td>
                <td className="px-2 py-1.5 text-right tnum">{r.clearing !== null ? `$${Number(r.clearing).toFixed(4)}` : '—'}</td>
                <td className="px-2 py-1.5 text-right">{r.filled === null ? '—' : r.filled ? <span className="text-emerald-400">yes</span> : 'no'}</td>
                <td className="px-2 py-1.5 text-right tnum">{usd(r.cost)}</td>
                <td className="px-2 py-1.5 text-right tnum">{usd(r.realized)}</td>
                <td className={`px-2 py-1.5 text-right tnum ${(r.pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{usd(r.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
