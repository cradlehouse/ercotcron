'use client'
/* Strip sheet for the 2028 2nd-6 long-term auction (bids Aug 18-20).
   Since NPRR1288 the auction sells individual months, so a strip is six
   monthly bids. Each path shows per-month: our rate, the ceiling (rate/1.5),
   the month's clearing price from PRIOR 2028 sequences, and margin. CSV
   emits one ERCOT-format row per selected month. Data: /strip_2028.json
   (strategy/strip_scan.py). */
import { useEffect, useMemo, useState } from 'react'

const MONTH_NAMES: Record<number, string> = { 7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec' }
const MONTH_DAYS: Record<number, number> = { 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31 }

type MonthCell = { rate: number; samples: number; clear: number | null; ceiling: number; hours: number; margin: number | null } | null
type StripRow = {
  source: string; sink: string; tou: string; hedge: string; prior_mw: number
  months: Record<string, MonthCell>
  strip_worth_per_mw: number; strip_cost_at_ceiling_per_mw: number
}
type StripData = { auction: string; bids: string; generated: string; rows: StripRow[] }

export default function StripSheet() {
  const [data, setData] = useState<StripData | null>(null)
  const [hedgeLens, setHedgeLens] = useState<'both' | 'OPT' | 'OBL'>('both')
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [mw, setMw] = useState<Record<string, number>>({})

  useEffect(() => {
    fetch('/strip_2028.json').then(r => r.json()).then(setData).catch(() => setData(null))
  }, [])

  // Same price discipline as the monthly sheet (588k-position study): the
  // durable edge lives under ~$0.75; up to $5 only with a 2x margin; above
  // $5 the market's aggregate record is a loss. A month QUALIFIES when its
  // margin clears 1.05 inside that zone; rich cells render muted and rows
  // rank by qualifying-month edge, not raw worth.
  const qualifies = (c: NonNullable<MonthCell>) => {
    if (c.margin === null || c.margin <= 1.05) return false
    const px = c.clear ?? c.ceiling
    return px < 0.75 || (px <= 5 && c.margin >= 2)
  }
  const rows = useMemo(() => {
    if (!data) return []
    const scored = data.rows
      .filter(r => hedgeLens === 'both' || r.hedge === hedgeLens)
      .map(r => {
        let edge = 0, nQual = 0
        for (const c of Object.values(r.months)) {
          if (c && qualifies(c)) { edge += (c.rate - c.ceiling) * c.hours; nQual++ }
        }
        return { r, edge, nQual }
      })
      .sort((a, b) => b.nQual - a.nQual || b.edge - a.edge)
    return scored.slice(0, 120)
  }, [data, hedgeLens])

  if (!data) return <div className="p-6 text-sm text-[#93a6ab]">loading strip sheet…</div>

  const key = (r: StripRow) => `${r.source}|${r.sink}|${r.tou}|${r.hedge}`

  function downloadCsv() {
    const lines = ['Bid ID,CRR ID,Account Holder,Source,Sink,MW,Price $/MWh,Time of Use,Buy/Sell,Hedge Type,Start Date,End Date,Description']
    for (const { r } of rows) {
      if (!checked[key(r)]) continue
      const q = mw[key(r)] ?? 1
      for (const [m, cell] of Object.entries(r.months)) {
        if (!cell || cell.ceiling < 0.05 || !qualifies(cell)) continue
        const mo = Number(m)
        lines.push(`,,XSAAIC,${r.source},${r.sink},${q},${cell.ceiling.toFixed(2)},${r.tou},BUY,${r.hedge},${mo}/1/2028,${mo}/${MONTH_DAYS[mo]}/2028,strip`)
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'strip_2028_bids.csv'
    a.click()
  }

  const nSel = rows.filter(x => checked[key(x.r)]).length

  return (
    <div className="min-h-screen bg-ink p-4 text-[#f2f6f6]">
      <div className="mb-1 flex flex-wrap items-baseline gap-3">
        <h1 className="text-[15px] font-semibold">2028 strip sheet — Jul–Dec 2028 long-term auction</h1>
        <span className="text-xs text-[#eda63a]">bids {data.bids}</span>
        <a href="/bids" className="ml-auto text-xs text-[#7d9096] hover:text-[#dbe4e6]">← September sheet</a>
      </div>
      <p className="mb-3 max-w-[90ch] text-[12.5px] text-[#93a6ab]">
        The auction sells individual months, so a strip is six bids. Each cell: our ceiling
        (worth ÷ 1.5) over the clearing price the SAME month drew in earlier 2028 sequences.
        History behind the far months is thin — sample count is shown; one summer is one sample.
        Price discipline applies here exactly as on the monthly sheet: months priced above the
        proven cheap zone (clear ≥ 75¢ without a 2× margin) render dimmed — across 588k scored
        market positions, that zone returned roughly zero to −13%. Rows rank by qualifying
        months, not raw worth.
      </p>
      <div className="mb-3 flex items-center gap-2 text-[11px]">
        <span className="text-[#7d9096]">Lens:</span>
        {(['both', 'OPT', 'OBL'] as const).map(h => (
          <button key={h} onClick={() => setHedgeLens(h)} className="rounded px-2 py-0.5"
            style={{ background: hedgeLens === h ? '#24404b' : 'transparent', color: hedgeLens === h ? '#f2f6f6' : '#7d9096' }}>
            {h === 'both' ? 'Both' : h === 'OPT' ? 'Options' : 'Obligations'}
          </button>
        ))}
        <button onClick={downloadCsv} disabled={nSel === 0}
          className="ml-auto rounded bg-[#eda63a] px-3 py-1 text-xs font-medium text-[#15242c] disabled:opacity-40">
          Download ERCOT CSV ({nSel} paths)
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-line bg-panel">
        <table className="w-full min-w-[1080px] border-collapse text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
              <th className="px-2 py-2"></th>
              <th className="px-2 py-2">Path</th>
              <th className="px-2 py-2">TOU · hedge</th>
              <th className="px-2 py-2">MW</th>
              {Object.entries(MONTH_NAMES).map(([m, n]) => <th key={m} className="px-2 py-2 text-right">{n} 28</th>)}
              <th className="px-2 py-2 text-right">Strip / MW</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ r, edge, nQual }) => {
              const k = key(r)
              return (
                <tr key={k} className="border-b border-line/50 align-top hover:bg-panel-2/40">
                  <td className="px-2 py-2">
                    <input type="checkbox" checked={!!checked[k]}
                      onChange={e => setChecked({ ...checked, [k]: e.target.checked })} />
                  </td>
                  <td className="px-2 py-2 font-mono text-[11.5px]">
                    {r.source} → {r.sink}
                    <div className="text-[10px] text-[#61767e]">{Math.round(r.prior_mw)} MW cleared in prior 2028 seqs</div>
                  </td>
                  <td className="px-2 py-2 text-[#93a6ab]">{r.tou} · {r.hedge}</td>
                  <td className="px-2 py-2">
                    <input type="number" min={0} value={mw[k] ?? 1}
                      onChange={e => setMw({ ...mw, [k]: Number(e.target.value) })}
                      className="w-14 rounded border border-line bg-ink px-1 py-0.5 text-right" />
                  </td>
                  {Object.keys(MONTH_NAMES).map(m => {
                    const c = r.months[m]
                    if (!c) return <td key={m} className="px-2 py-2 text-right text-[#3a4f58]">—</td>
                    const good = qualifies(c)
                    const px = c.clear ?? c.ceiling
                    const rich = px >= 0.75 && !good
                    return (
                      <td key={m} className="px-2 py-2 text-right font-mono text-[11px]"
                          style={rich ? { opacity: 0.35 } : undefined}
                          title={rich ? 'outside the proven price zone — market pays ~0% or worse here' : undefined}>
                        <div className={good ? 'text-emerald-400' : 'text-[#dbe4e6]'}>${c.ceiling.toFixed(2)}</div>
                        <div className="text-[10px] text-[#61767e]">
                          clr {c.clear !== null ? `$${c.clear.toFixed(2)}` : '—'}
                          {c.samples < 2 ? ' · 1 sample' : ''}
                        </div>
                      </td>
                    )
                  })}
                  <td className="px-2 py-2 text-right font-mono text-[11.5px]">
                    <div className={nQual > 0 ? 'text-emerald-400' : 'text-[#7d9096]'}>
                      {nQual}/6 months qualify
                    </div>
                    <div className="text-[10px] text-[#61767e]">
                      ${edge.toFixed(0)}/MW edge in-zone · ${r.strip_worth_per_mw.toFixed(0)} raw worth
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 max-w-[90ch] text-[11px] leading-relaxed text-[#61767e]">
        Ceilings build in the 50% margin rule per month. Far-month history is one or two
        calendar samples — treat single-sample cells as sketches, not prices. The CSV emits one
        row per month at each month&apos;s own ceiling; edit quantities before upload. Not a forecast.
      </p>
    </div>
  )
}
