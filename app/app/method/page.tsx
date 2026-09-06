'use client'
// The method scored against itself, visible to every member — every
// snapshotted sheet row's counterfactual (would the reference limit have
// filled; what delivery paid), including the red don't-bid calls. This IS
// the self-scoring methodology §10 pre-registers.
import { Fragment, useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'
import { DailyChart, type DailyRow } from '../../daily-chart'

type SheetAgg = { sheet: string; tier: string; rows: number; snapshot_at: string; filled: number | null; cost: number | null; realized: number | null; pnl: number | null }
type Row = { sheet: string; source: string; sink: string; time_of_use: string; hedge_type: string; tier: string; ref_limit: number | null; suggested_mw: number | null; clearing: number | null; filled: boolean | null; cost: number | null; realized: number | null; pnl: number | null }
type Score = { sheets: SheetAgg[]; rows: Row[] }
type Prog = { grp: string; source: string; sink: string; tou: string; hedge: string; tier: string; bid: number | null; clearing: number | null; mw: number; delivery: string; status: string; hours: number; cost: number | null; paid: number | null }

const usd = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${Number(v).toLocaleString()}`)
const TIER_COLOR: Record<string, string> = { green: 'text-emerald-400', amber: 'text-amber-400', red: 'text-red-400' }

export default function MethodScore() {
  const [score, setScore] = useState<Score | null>(null)
  const [prog, setProg] = useState<Prog[] | null>(null)
  const [openEst, setOpenEst] = useState<string | null>(null)
  const [estDaily, setEstDaily] = useState<Record<string, DailyRow[] | 'loading'>>({})

  async function toggleEst(r: Prog) {
    const key = `${r.grp}|${r.source}|${r.sink}|${r.tou}|${r.hedge}`
    if (openEst === key) { setOpenEst(null); return }
    setOpenEst(key)
    if (!estDaily[key]) {
      setEstDaily(d => ({ ...d, [key]: 'loading' }))
      const { data } = await sb.rpc('get_path_daily', {
        p_src: r.source, p_snk: r.sink, p_tou: r.tou, p_hedge: r.hedge,
        p_month: `${r.delivery}-01`,
      })
      const rows = ((data as { d: string; hours: number; paid_per_mwh: number }[]) ?? []).map(x => ({
        d: x.d, hours: x.hours,
        paid_in: Math.round((r.clearing ?? 0) * x.hours * r.mw),
        paid_out: Math.round(x.paid_per_mwh * r.mw),
      }))
      setEstDaily(d => ({ ...d, [key]: rows }))
    }
  }
  const [state, setState] = useState<'loading' | 'denied' | 'ok'>('loading')

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      const { data: s, error } = await sb.rpc('get_method_score')
      if (error || !s) { setState('denied'); return }
      setScore(s as Score)
      setState('ok')
      // admin-only live progress; null for everyone else
      const { data: pr } = await sb.rpc('get_method_progress')
      if (pr) setProg(pr as Prog[])
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

      {prog && prog.length > 0 && (() => {
        const groups = [...new Set(prog.map(p => p.grp))]
        return (
          <div className="mt-6">
            <h2 className="text-[14px] font-medium">Pre-auction estimates — live progress <span className="ml-2 text-[10px] uppercase tracking-wider text-[#61767e]">admin</span></h2>
            {groups.map(g => {
              const rows = prog.filter(p => p.grp === g)
              const running = rows.filter(r => r.status === 'running')
              const cost = running.reduce((a, r) => a + (r.cost ?? 0), 0)
              const paid = running.reduce((a, r) => a + (r.paid ?? 0), 0)
              const missed = rows.filter(r => r.status.startsWith('missed —'))
              const mCost = missed.reduce((a, r) => a + (r.cost ?? 0), 0)
              const mPaid = missed.reduce((a, r) => a + (r.paid ?? 0), 0)
              return (
                <div key={g} className="mt-3">
                  <div className="flex flex-wrap items-baseline gap-3 text-[13px]">
                    <span className="font-medium text-[#dbe4e6]">{g}</span>
                    <span className="text-[11.5px] text-[#7d9096]">
                      {rows.length} estimates · {running.length} running
                      {running.length > 0 && <> · ours: {`$${cost.toLocaleString()} in / $${paid.toLocaleString()} out`} ({cost > 0 ? Math.round((paid / cost) * 100) : 0}%)</>}
                      {missed.length > 0 && <> · <span className="text-red-400/80">the market&apos;s {missed.length} buys at prices we refused: {`$${mCost.toLocaleString()} in / $${mPaid.toLocaleString()} out`} ({mCost > 0 ? Math.round((mPaid / mCost) * 100) : 0}%)</span></>}
                    </span>
                  </div>
                  <div className="mt-1 overflow-x-auto rounded border border-line bg-panel">
                    <table className="w-full min-w-[860px] border-collapse text-[11.5px]">
                      <tbody>
                        {rows.map((r, i) => {
                          const key = `${r.grp}|${r.source}|${r.sink}|${r.tou}|${r.hedge}`
                          const canOpen = r.status === 'running' || r.status.startsWith('missed —')
                          const isOpen = openEst === key
                          const dd = estDaily[key]
                          return (
                          <Fragment key={i}>
                          <tr onClick={() => canOpen && toggleEst(r)}
                              className={`border-b border-line/40 text-[#93a6ab] last:border-0 ${canOpen ? 'cursor-pointer hover:bg-panel-2/40' : ''} ${isOpen ? 'bg-panel-2/30' : ''}`}>
                            <td className="px-2 py-1 font-mono text-[11px] text-[#dbe4e6]">
                              {canOpen && <span className="mr-1 text-[10px] text-[#eda63a]">{isOpen ? '▾' : '▸'}</span>}
                              {r.source} → {r.sink}</td>
                            <td className="px-2 py-1">{r.tou} · {r.hedge}</td>
                            <td className="px-2 py-1">{r.delivery}</td>
                            <td className="px-2 py-1 text-right tnum">{r.bid !== null ? `$${Number(r.bid).toFixed(2)}` : '—'}{r.clearing !== null ? ` / $${Number(r.clearing).toFixed(4)}` : ''}</td>
                            <td className="px-2 py-1 text-right tnum">{Number(r.mw)} MW</td>
                            <td className={`px-2 py-1 ${r.status === 'running' ? 'text-emerald-400' : r.status.startsWith('missed —') ? 'text-red-400/80' : r.status === 'missed' ? 'text-[#61767e]' : 'text-amber-400'}`}>{r.status}</td>
                            <td className="px-2 py-1 text-right tnum">{canOpen && r.cost !== null ? `$${(r.cost ?? 0).toLocaleString()} in` : ''}</td>
                            <td className="px-2 py-1 text-right tnum">{canOpen && r.paid !== null ? `$${(r.paid ?? 0).toLocaleString()} out` : ''}</td>
                          </tr>
                          {isOpen && (
                            <tr className="border-b border-line/40">
                              <td colSpan={8} className="bg-ink/40 px-3 py-3">
                                {dd === 'loading' || !dd
                                  ? <div className="text-[12px] text-[#7d9096]">pulling the daily record…</div>
                                  : dd.length === 0
                                    ? <div className="text-[12px] text-[#93a6ab]">No settled days yet this month for this block.</div>
                                    : <DailyChart rows={dd} month={r.delivery} />}
                              </td>
                            </tr>
                          )}
                          </Fragment>
                        )})}
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })}
          </div>
        )
      })()}

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
