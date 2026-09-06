'use client'
// The model's book — every paper batch the engine put on the record BEFORE
// auction results, and what actually happened: fills, running month-to-date
// while a month delivers, final P&L when it settles, misses and passed-up
// wins with equal billing.
//
// This is a track record, not a recommendation. Bids are hypothetical, stored
// append-only, scored by the same rules pre-registered in the methodology
// (§10). Member-gated for beta; the public Scorecard grows from this surface.
import { useEffect, useMemo, useState } from 'react'
import { sb } from '@/lib/supabase'

type Bid = {
  batch_id: string; auction_name: string; submitted_on: string
  source: string; sink: string; time_of_use: string; hedge_type: string
  mw: number | string; bid_price: number | string
  clearing_price: number | string | null; cleared: boolean | null
  delivery_month: string | null
  realized_value: number | string | null; pnl: number | string | null
  running_value: number | string | null; running_hours: number | null
  marked_through: string | null
}

const n = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined ? null : Number(v)
const usd = (v: number | null, dp = 2) => (v === null ? '—' : `$${v.toFixed(dp)}`)
const money = (v: number) =>
  `${v < 0 ? '−' : ''}$${Math.abs(v) >= 1000 ? Math.round(Math.abs(v)).toLocaleString('en-US') : Math.abs(v).toFixed(0)}`

// Friendly batch titles; anything unlisted renders its raw id.
const BATCH_TITLE: Record<string, string> = {
  '2026-10-monthly-model-1': 'October 2026 monthly — the model’s picks',
  '2026-09-monthly-shadowprice-recon-1': 'September 2026 monthly — the model’s picks (reconstruction)',
  '2026-09-monthly-steve-1': 'September 2026 monthly — design partner’s live ticket',
}

export default function ModelBook() {
  const [bids, setBids] = useState<Bid[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    sb.rpc('get_model_book').then(({ data, error }) => {
      if (error) setError(error.message)
      else setBids(data as Bid[])
    })
  }, [])

  const batches = useMemo(() => {
    const by = new Map<string, Bid[]>()
    for (const b of bids ?? []) {
      if (!by.has(b.batch_id)) by.set(b.batch_id, [])
      by.get(b.batch_id)!.push(b)
    }
    return [...by.entries()]
  }, [bids])

  if (error) return <div className="p-6 text-sm text-red-400">{error}</div>
  if (!bids) return <div className="p-6 text-sm text-[#7d9096]">loading the record…</div>

  return (
    <div className="mx-auto max-w-5xl px-2 py-2 text-[#f2f6f6]">
      <h1 className="text-lg font-medium">The model&apos;s book</h1>
      <p className="mt-1 text-[12.5px] text-[#7d9096]">
        Batches below are bids stored before results posted. The{' '}
        <a href="/app/method" className="text-[#eda63a] hover:underline">full method score</a>{' '}
        grades every row of every published sheet — including the don&apos;t-bid calls.
      </p>
      <p className="mt-1 max-w-[80ch] text-[12.5px] leading-relaxed text-[#93a6ab]">
        Every batch of paper bids the engine put on the record <i>before</i> results posted,
        and what happened next. Nothing here can be edited after the fact — the table refuses
        updates to bid fields by database rule. Misses stay on the page next to hits; that is
        the point.
      </p>

      {batches.map(([batchId, rows]) => {
        const resultsIn = rows.some(r => r.cleared !== null)
        const fills = rows.filter(r => r.cleared)
        const inDelivery = rows.some(r => r.running_value !== null && n(r.pnl) === null)
        const settledPnl = rows.reduce((s, r) => s + (n(r.pnl) ?? 0), 0)
        const anySettled = rows.some(r => n(r.pnl) !== null)
        const runNet = fills.reduce((s, r) => {
          const rv = n(r.running_value); const cp = n(r.clearing_price); const h = r.running_hours
          if (rv === null || cp === null || h === null) return s
          return s + (rv - cp * h) * (n(r.mw) ?? 0)
        }, 0)
        const markedThrough = rows.map(r => r.marked_through).filter(Boolean).sort().at(-1)
        return (
          <section key={batchId} className="mt-6 rounded border border-line bg-panel/50 p-4">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-[14px] font-medium">{BATCH_TITLE[batchId] ?? batchId}</h2>
              <span className="text-[11px] text-[#61767e]">
                {rows.length} bids · on record {rows[0].submitted_on} · {rows[0].auction_name}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-[#93a6ab]">
              {!resultsIn && <span>auction results not posted yet — fills unknown</span>}
              {resultsIn && <span>filled <span className="text-[#dbe4e6]">{fills.length}/{rows.length}</span></span>}
              {inDelivery && markedThrough && (
                <span>
                  running net on fills{' '}
                  <span className={runNet >= 0 ? 'text-emerald-400' : 'text-red-400'}>{money(runNet)}</span>
                  {' '}through {markedThrough} <span className="text-[#61767e]">(partial month — not the score)</span>
                </span>
              )}
              {anySettled && (
                <span>settled P&L{' '}
                  <span className={settledPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>{money(settledPnl)}</span>
                </span>
              )}
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-[12px]">
                <thead>
                  <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#61767e]">
                    <th className="px-2 py-1.5 font-medium">Path</th>
                    <th className="px-2 py-1.5 font-medium">Block · type</th>
                    <th className="px-2 py-1.5 text-right font-medium">MW</th>
                    <th className="px-2 py-1.5 text-right font-medium">Our limit</th>
                    <th className="px-2 py-1.5 text-right font-medium">Cleared at</th>
                    <th className="px-2 py-1.5 text-right font-medium">Fill</th>
                    <th className="px-2 py-1.5 text-right font-medium">Banked so far / result</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const cp = n(r.clearing_price)
                    const rv = n(r.running_value)
                    const pnl = n(r.pnl)
                    const mw = n(r.mw) ?? 0
                    const runNetRow = r.cleared && rv !== null && cp !== null && r.running_hours !== null
                      ? (rv - cp * r.running_hours) * mw : null
                    return (
                      <tr key={i} className="border-b border-line/50 text-[#93a6ab] last:border-0">
                        <td className="px-2 py-1.5 text-[#dbe4e6]">{r.source} <span className="text-[#61767e]">→</span> {r.sink}</td>
                        <td className="px-2 py-1.5">{r.time_of_use} · {r.hedge_type}</td>
                        <td className="px-2 py-1.5 text-right tnum">{mw}</td>
                        <td className="px-2 py-1.5 text-right tnum">{usd(n(r.bid_price))}</td>
                        <td className="px-2 py-1.5 text-right tnum">{cp === null ? (resultsIn ? 'never traded' : '—') : usd(cp, 4)}</td>
                        <td className="px-2 py-1.5 text-right">
                          {r.cleared === null ? '—' : r.cleared
                            ? <span className="text-emerald-400">filled</span>
                            : <span className="text-[#61767e]">missed</span>}
                        </td>
                        <td className="px-2 py-1.5 text-right tnum">
                          {pnl !== null
                            ? <span className={pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>{money(pnl)} settled</span>
                            : runNetRow !== null
                              ? <span className={runNetRow >= 0 ? 'text-emerald-400' : 'text-red-400'}>{money(runNetRow)}</span>
                              : r.cleared === false && rv !== null
                                ? <span className="text-[#61767e]">would be {money((rv - (cp ?? 0) * (r.running_hours ?? 0)) * mw)}</span>
                                : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}

      <p className="mt-6 max-w-[90ch] text-[10.5px] leading-relaxed text-[#61767e]">
        HYPOTHETICAL PERFORMANCE DISCLOSURE: these are paper bids — no actual bids were
        submitted and no positions were held. Fills are assumed at posted clearing prices,
        capped at awarded volume. Hypothetical results have inherent limitations and do not
        reflect actual market participation; no representation is made that any account will
        or is likely to achieve similar results. Running figures are partial-month description;
        the score is struck only when a delivery month settles in full. Nothing on this page is
        a recommendation to buy or sell anything.
      </p>
    </div>
  )
}
