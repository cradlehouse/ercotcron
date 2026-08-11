'use client'

// The order ticket: turns valuations into a submittable auction bid.
//
// Every row answers the operational questions in order — bid this price, this
// many MW, costing at most this, historically returning that — and the
// download button emits the exact CSV the ERCOT CRR interface accepts (column
// order from ERCOT's own sample upload file). Quantities are editable because
// sizing is Steve's call: our magnitude estimates are measurably unreliable
// (61% within 2x), so the tool prices and the trader sizes.

import { useMemo, useState } from 'react'

export interface TicketRow {
  key: string
  origin: 'book' | 'discovery' | 'market'
  tier: 'green' | 'amber'
  source: string
  sink: string
  tou: string
  hedge: string
  ceiling: number          // the bid price
  worth: number
  cleared: number | null   // usual auction cost; null = never seen clear
  marginX: number | null
  pctHours: number | null
  prevBid: number | null
  prevMw: number | null
  suggestedMw: number
  holders: number | null   // winning firms holding (discovery only)
  flag: string             // plain-english caution, '' if none
  overbidNote: string      // '' unless his old bid exceeded the ceiling
}

export interface AuctionMeta {
  name: string
  opens: string
  closes: string
  deliveryStart: string    // e.g. 9/1/2026 — goes into the CSV verbatim
  deliveryEnd: string
  deliveryLabel: string
  daysLeft: number
  hours: Record<string, number>
  holder: string
}

const usd = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : `$${v.toFixed(dp)}`
const money = (v: number) =>
  v >= 1000 ? `$${Math.round(v).toLocaleString('en-US')}` : `$${v.toFixed(0)}`

export function Ticket({ rows, auction }: { rows: TicketRow[]; auction: AuctionMeta }) {
  const [qty, setQty] = useState<Record<string, number>>(() =>
    Object.fromEntries(rows.map((r) => [r.key, r.suggestedMw])),
  )
  const [checked, setChecked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(rows.map((r) => [r.key, r.tier === 'green'])),
  )

  const derived = useMemo(() => {
    const out: Record<string, { hours: number; maxCost: number; likelyCost: number; histReturn: number }> = {}
    for (const r of rows) {
      const h = auction.hours[r.tou] ?? 0
      const q = qty[r.key] ?? 0
      out[r.key] = {
        hours: h,
        maxCost: q * h * r.ceiling,
        likelyCost: q * h * (r.cleared ?? r.ceiling),
        histReturn: q * h * r.worth,
      }
    }
    return out
  }, [rows, qty, auction.hours])

  const selected = rows.filter((r) => checked[r.key] && (qty[r.key] ?? 0) > 0)
  const totals = selected.reduce(
    (acc, r) => {
      const d = derived[r.key]
      acc.maxCost += d.maxCost
      acc.likelyCost += d.likelyCost
      acc.histReturn += d.histReturn
      return acc
    },
    { maxCost: 0, likelyCost: 0, histReturn: 0 },
  )

  function downloadCsv() {
    const head = 'Bid ID,CRR ID,Account Holder,Source,Sink,MW,Price $/MWh,Time of Use,Buy/Sell,Hedge Type,Start Date,End Date,Description'
    const lines = selected.map((r) =>
      `,,${auction.holder},${r.source},${r.sink},${qty[r.key]},${r.ceiling.toFixed(2)},${r.tou},BUY,${r.hedge},${auction.deliveryStart},${auction.deliveryEnd},ceiling`,
    )
    const blob = new Blob([[head, ...lines].join('\r\n') + '\r\n'], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `bids_${auction.name.replaceAll('.', '_')}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const green = rows.filter((r) => r.tier === 'green')
  const amber = rows.filter((r) => r.tier === 'amber')

  const Row = ({ r }: { r: TicketRow }) => {
    const d = derived[r.key]
    const net = d.histReturn - d.likelyCost
    return (
      <tr className={`border-b border-line/60 last:border-0 ${checked[r.key] ? '' : 'opacity-45'}`}>
        <td className="px-2 py-2.5 align-top">
          <input
            type="checkbox"
            checked={!!checked[r.key]}
            onChange={(e) => setChecked((c) => ({ ...c, [r.key]: e.target.checked }))}
            className="mt-1 h-4 w-4 accent-emerald-500"
            aria-label={`include ${r.source} to ${r.sink}`}
          />
        </td>
        <td className="px-2 py-2.5">
          <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium text-zinc-200">
            <span>{r.source}</span><span className="text-amber-500">→</span><span>{r.sink}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-zinc-600">
            {r.tou} · {r.hedge} · {d.hours} hrs in Sep
            {r.origin === 'discovery' && r.holders ? ` · held by ${r.holders} winning firm${r.holders > 1 ? 's' : ''}` : r.origin === 'market' ? ` · market scan · cleared in ${r.holders ?? '?'} auctions` : ''}
          </div>
          {r.overbidNote && <div className="mt-1 text-[11px] text-amber-400">{r.overbidNote}</div>}
          {r.flag && <div className="mt-1 text-[11px] text-zinc-500">{r.flag}</div>}
        </td>
        <td className="px-2 py-2.5 text-right align-top">
          <div className="tnum text-[16px] font-bold text-emerald-300">{usd(r.ceiling)}</div>
          <div className="text-[10px] text-zinc-600">
            {r.cleared !== null
              ? `going rate ~${usd(r.cleared)}${r.marginX !== null ? ` (${r.marginX.toFixed(0)}× under your limit)` : ''}`
              : 'no clearing history'}
          </div>
        </td>
        <td className="px-2 py-2.5 text-right align-top">
          <input
            type="number" min={0} step={1} value={qty[r.key] ?? 0}
            onChange={(e) => setQty((q) => ({ ...q, [r.key]: Math.max(0, Number(e.target.value)) }))}
            className="w-16 rounded border border-line bg-transparent px-1.5 py-1 text-right tnum text-[13px] text-zinc-200"
            aria-label="MW quantity"
          />
          <div className="mt-0.5 text-[10px] text-zinc-600">
            {r.prevMw ? `you held ${r.prevMw.toFixed(0)}` : 'new path'}
          </div>
        </td>
        <td className="px-2 py-2.5 text-right align-top tnum text-zinc-300">{money(d.likelyCost)}
          <div className="text-[10px] text-zinc-600 tnum">
            {qty[r.key] ?? 0} MW × {d.hours} h × {r.cleared !== null ? usd(r.cleared) : usd(r.ceiling)}
          </div>
        </td>
        <td className="px-2 py-2.5 text-right align-top tnum text-zinc-300">{money(d.histReturn)}
          <div className={`text-[10px] tnum ${net >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {net >= 0 ? '+' : ''}{money(net).replace('$', '$')} net
          </div>
        </td>
        <td className="px-2 py-2.5 text-right align-top tnum text-zinc-500">{money(d.maxCost)}
          <div className="text-[10px] text-zinc-600 tnum">× {usd(r.ceiling)}</div>
        </td>
      </tr>
    )
  }

  const Head = () => (
    <thead>
      <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
        <th className="w-8 px-2 py-2" />
        <th className="px-2 py-2 font-medium">Path</th>
        <th className="px-2 py-2 text-right font-medium">Your limit<br /><span className="normal-case text-zinc-600">$/MWh — not what you pay</span></th>
        <th className="px-2 py-2 text-right font-medium">MW</th>
        <th className="px-2 py-2 text-right font-medium">Likely cost<br /><span className="normal-case text-zinc-600">at its going rate</span></th>
        <th className="px-2 py-2 text-right font-medium">If the past year repeats</th>
        <th className="px-2 py-2 text-right font-medium">Worst case<br /><span className="normal-case text-zinc-600">clears at your limit</span></th>
      </tr>
    </thead>
  )

  return (
    <div className="space-y-5">
      <div className="sticky top-0 z-10 -mx-1 rounded-lg border border-line bg-panel/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">selected</div>
            <div className="tnum text-[15px] font-semibold text-zinc-200">{selected.length} bids</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">likely outlay</div>
            <div className="tnum text-[15px] font-semibold text-zinc-200">{money(totals.likelyCost)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">history returned</div>
            <div className={`tnum text-[15px] font-semibold ${totals.histReturn >= totals.likelyCost ? 'text-emerald-300' : 'text-red-400'}`}>
              {money(totals.histReturn)}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">max at ceilings</div>
            <div className="tnum text-[15px] font-semibold text-zinc-400">{money(totals.maxCost)}</div>
          </div>
          <button
            onClick={downloadCsv}
            disabled={selected.length === 0}
            className="ml-auto rounded-md bg-emerald-600 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-40"
          >
            Download bid file ({selected.length})
          </button>
        </div>
        <p className="mt-2 text-[11px] text-zinc-600">
          CSV matches ERCOT&apos;s CRR upload format · account {auction.holder} · delivery{' '}
          {auction.deliveryLabel} · max outlay is what you pay only if every path clears at your
          full bid — the historical norm is the likely column.
        </p>
      </div>

      {rows.length > 0 && (() => {
        const ex = green[0] ?? amber[0]
        const eh = auction.hours[ex.tou] ?? 0
        const eq = ex.suggestedMw
        return (
          <div className="rounded-lg border border-line bg-panel px-4 py-3 text-[12.5px] text-zinc-400">
            <span className="font-semibold text-zinc-200">How to read a row, using the first one: </span>
            a CRR here is a strip of {eh} {ex.tou} hours in September. {eq} MW means you are
            buying {eq} × {eh} = {(eq * eh).toLocaleString()} MWh. Your limit of {usd(ex.ceiling)}
            /MWh is the most you authorise — <span className="text-zinc-200">everyone pays the
            same clearing price, not their bid</span>, and this path has recently cleared
            around {ex.cleared !== null ? usd(ex.cleared) : 'unknown'}, so you would likely pay
            about {money(eq * eh * (ex.cleared ?? ex.ceiling))} in total. The worst case —
            it clears exactly at your limit — is {money(eq * eh * ex.ceiling)}. Bidding a low
            number instead does not save money; it only loses you the path in any month someone
            else spots it too.
          </div>
        )
      })()}

      {green.length > 0 && (
        <section>
          <div className="mb-1 flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold text-zinc-200">Verified value</h2>
            <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
              bid the shown price
            </span>
          </div>
          <p className="mb-3 max-w-[70ch] text-[12.5px] text-zinc-500">
            Worth more than the auction has charged, on real clearing history. Enter the green
            figure as the bid — the auction charges the clearing price, not your bid, so bidding
            the full ceiling maximises wins at no extra cost.
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full min-w-[880px] border-collapse"><Head /><tbody>
              {green.map((r) => <Row key={r.key} r={r} />)}
            </tbody></table>
          </div>
        </section>
      )}

      {amber.length > 0 && (
        <section>
          <div className="mb-1 flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold text-zinc-200">Unverified or flagged</h2>
            <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
              size small if at all
            </span>
          </div>
          <p className="mb-3 max-w-[70ch] text-[12.5px] text-zinc-500">
            Positive value on paper, but either the path has never been seen clearing an auction —
            so the &ldquo;cheap&rdquo; cannot be verified — or a caution applies. Unchecked by
            default; deliberately small suggested sizes.
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full min-w-[880px] border-collapse"><Head /><tbody>
              {amber.map((r) => <Row key={r.key} r={r} />)}
            </tbody></table>
          </div>
        </section>
      )}
    </div>
  )
}
