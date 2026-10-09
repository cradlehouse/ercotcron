'use client'

// The order ticket: turns valuations into a submittable auction bid.
//
// Every row answers the operational questions in order — bid this price, this
// many MW, costing at most this, historically returning that — and the
// download button emits the exact CSV the ERCOT CRR interface accepts (column
// order from ERCOT's own sample upload file). Quantities are editable because
// sizing is Steve's call: our magnitude estimates are measurably unreliable
// (61% within 2x), so the tool prices and the trader sizes.

import { useEffect, useMemo, useState } from 'react'
import { usdFixed as usd } from '@/lib/fmt'

export interface TicketRow {
  key: string
  origin: 'book' | 'discovery' | 'market'
  tier: 'green' | 'amber'
  source: string
  sink: string
  tou: string
  hedge: string
  offeredMw: number | null // MW already offered for sale (latest auction file)
  ceiling: number          // the bid price
  worth: number            // annual-mean hourly payout (context, not the EV)
  typical: number | null   // month-honest payout: median of per-month means,
                           // capped by the actual delivery month's history and the recent three
                           // months — the same base the ceiling is priced off
  cleared: number | null   // usual auction cost; null = never seen clear
  marginX: number | null
  pctHours: number | null
  prevBid: number | null
  prevMw: number | null
  suggestedMw: number
  holders: number | null   // winning firms holding (discovery only)
  maxMw?: number | null    // most MW any single auction awarded — liquidity cap
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
  holder: string           // default Account Holder for the CSV ('' = ask)
  holderOptions: string[]  // every code the member holds an approved claim on
}

type Lens = 'both' | 'OPT' | 'OBL' | 'selected'
type Draft = { checked: Record<string, boolean>; qty: Record<string, number>; holder: string }

// The draft lives in this browser only (localStorage), keyed by auction — never
// on our server: a table of members' intended bids is exactly the book data
// the charter says goes to them and nobody else. Storage can be absent
// (private window, blocked site data), so every access is guarded.
const draftKey = (auction: string) => `sp-draft:${auction}`
function loadDraft(auction: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(draftKey(auction))
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch { return null }
}
function saveDraft(auction: string, d: Draft) {
  try { window.localStorage.setItem(draftKey(auction), JSON.stringify(d)) } catch { /* no storage */ }
}
function clearDraft(auction: string) {
  try { window.localStorage.removeItem(draftKey(auction)) } catch { /* no storage */ }
}

// ERCOT CRR account codes are short all-caps tokens (e.g. XSAAIC).
const HOLDER_RE = /^[A-Z0-9]{2,12}$/
const SHORTLIST_N = 25

const money = (v: number) =>
  v >= 1000 ? `$${Math.round(v).toLocaleString('en-US')}` : `$${v.toFixed(0)}`

const MONTH_LONG: Record<string, string> = {
  JAN: 'January', FEB: 'February', MAR: 'March', APR: 'April', MAY: 'May', JUN: 'June',
  JUL: 'July', AUG: 'August', SEP: 'September', OCT: 'October', NOV: 'November', DEC: 'December',
}

export function Ticket({ rows, auction }: { rows: TicketRow[]; auction: AuctionMeta }) {
  const monthShort = auction.name.split('.')[1] ?? ''
  const monthLong = MONTH_LONG[monthShort] ?? monthShort
  // Defaults are the same for every viewer (green checked, liquidity-derived
  // MW); a saved draft for this auction overrides them row by row. Ticket only
  // mounts after the client-side sheet fetch, so reading storage here is safe.
  const defaultQty = () => Object.fromEntries(rows.map((r) => [r.key, r.suggestedMw]))
  const defaultChecked = () => Object.fromEntries(rows.map((r) => [r.key, r.tier === 'green']))
  const saved = useMemo(() => (typeof window === 'undefined' ? null : loadDraft(auction.name)), [auction.name])
  const [qty, setQty] = useState<Record<string, number>>(() => {
    const q = defaultQty()
    for (const [k, v] of Object.entries(saved?.qty ?? {})) if (k in q) q[k] = v
    return q
  })
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const c = defaultChecked()
    for (const [k, v] of Object.entries(saved?.checked ?? {})) if (k in c) c[k] = v
    return c
  })
  const [holder, setHolder] = useState<string>(() => saved?.holder || auction.holder)
  const [restored] = useState(() => saved !== null)
  useEffect(() => {
    saveDraft(auction.name, { checked, qty, holder })
  }, [auction.name, checked, qty, holder])
  function resetDraft() {
    clearDraft(auction.name)
    setQty(defaultQty())
    setChecked(defaultChecked())
    setHolder(auction.holder)
  }
  // Hedge lens: obligations returned +22.3% as a class over 17 scored months
  // while options lost -7.6% — the toggle exists so the sheet's best OBL
  // candidates are one click away instead of buried among the options.
  // 'selected' shows exactly what the file will contain.
  const [hedgeLens, setHedgeLens] = useState<Lens>('both')
  const [search, setSearch] = useState('')
  const [showFile, setShowFile] = useState(false)

  // The budget allocator (budget in → sized MW out) was REMOVED per the
  // pre-launch legal review (action A10): a tool converting a subscriber's
  // stated capital into per-path quantities is individualized sizing, which
  // conflicts with the impersonal-publisher posture until counsel clears it
  // and clickwrap terms are live. MW inputs remain subscriber-set; defaults
  // are the same uniform liquidity-derived figures for every viewer.

  const derived = useMemo(() => {
    const out: Record<string, { hours: number; maxCost: number; likelyCost: number; histReturn: number }> = {}
    for (const r of rows) {
      const h = auction.hours[r.tou] ?? 0
      const q = qty[r.key] ?? 0
      out[r.key] = {
        hours: h,
        maxCost: q * h * r.ceiling,
        likelyCost: q * h * (r.cleared ?? r.ceiling),
        histReturn: q * h * (r.typical ?? r.worth),
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
      `,,${holder},${r.source},${r.sink},${qty[r.key]},${r.ceiling.toFixed(2)},${r.tou},BUY,${r.hedge},${auction.deliveryStart},${auction.deliveryEnd},ceiling`,
    )
    const blob = new Blob([[head, ...lines].join('\r\n') + '\r\n'], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `bids_${auction.name.replaceAll('.', '_')}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const needle = search.trim().toUpperCase()
  const lens = (r: TicketRow) =>
    (hedgeLens === 'both' || (hedgeLens === 'selected' ? !!checked[r.key] : r.hedge === hedgeLens)) &&
    (!needle || r.source.includes(needle) || r.sink.includes(needle))
  // Selected rows the current view hides — they still go in the file, so say so.
  const hiddenSelected = selected.filter((r) => !lens(r)).length
  const holderOk = HOLDER_RE.test(holder)
  // EV% — the lead number: the TYPICAL month's payout per $1 paid at the
  // price you'd likely pay (the usual clearing price; your limit when no
  // history). The typical (median of per-month means, delivery-month-capped,
  // recency-capped) is the scan's own honest base — the annual mean is only
  // the fallback where no typical was published, because the July holdout
  // showed it overstates a single month ~10x on spike paths. Rounded to 5s
  // (magnitudes ~61% within 2x); suppressed under a 25c clear — a penny
  // denominator turns any numerator into four-digit noise.
  const evOf = (r: TicketRow) => {
    const px = r.cleared ?? r.ceiling
    if (!px || px <= 0 || px < 0.25) return null
    return Math.round((((r.typical ?? r.worth) - px) / px) * 100 / 5) * 5
  }
  const evRank = useMemo(() => {
    const evs = rows.map(r => ({ k: r.key, ev: evOf(r) }))
      .filter(x => x.ev !== null)
      .sort((a, b) => (b.ev ?? 0) - (a.ev ?? 0))
    const m: Record<string, number> = {}
    evs.forEach((x, i) => { m[x.k] = Math.max(1, Math.ceil(((i + 1) / evs.length) * 100)) })
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows])
  // Liquidity gates ranking (Sep-2026 reconstruction lesson: a pure-EV top-12
  // drew ZERO fills — 10 of 12 paths never traded). Rows with real clearing
  // history rank above no-history rows at any EV.
  const byEv = (a: TicketRow, b: TicketRow) => {
    const liq = Number(b.cleared !== null) - Number(a.cleared !== null)
    if (liq !== 0) return liq
    return (evOf(b) ?? -999) - (evOf(a) ?? -999)
  }
  const green = rows.filter((r) => r.tier === 'green' && lens(r)).sort(byEv)
  const amber = rows.filter((r) => r.tier === 'amber' && lens(r)).sort(byEv)

  // A render function, not a nested component: a component declared inside
  // Ticket is a new type every render, so React remounted every row on each
  // keystroke and the MW input lost focus mid-number.
  const renderRow = (r: TicketRow) => {
    const d = derived[r.key]
    const net = d.histReturn - d.likelyCost
    const on = !!checked[r.key]
    return (
      <tr key={r.key} className={`border-b border-line/60 last:border-0 ${on ? 'bg-emerald-500/[0.05]' : ''}`}>
        <td className={`border-l-2 px-2 py-2.5 align-top ${on ? 'border-emerald-500' : 'border-transparent'}`}>
          <input
            type="checkbox"
            checked={!!checked[r.key]}
            onChange={(e) => setChecked((c) => ({ ...c, [r.key]: e.target.checked }))}
            className="mt-1 h-4 w-4 accent-emerald-500"
            aria-label={`include ${r.source} to ${r.sink}`}
          />
        </td>
        <td className="px-2 py-2.5">
          <a className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium text-zinc-200 hover:text-white"
             href={`/path?src=${encodeURIComponent(r.source)}&snk=${encodeURIComponent(r.sink)}`}
             target="_blank" rel="noopener"
             title="open this path's dossier in a new tab — your draft stays here">
            <span>{r.source}</span><span className="text-amber-500">→</span><span>{r.sink}</span>
          </a>
          <div className="mt-0.5 text-[11px] text-zinc-600">
            {r.tou} · {r.hedge} · {d.hours} hrs in {monthShort}{r.offeredMw ? ` · ${Math.round(r.offeredMw)} MW offered for sale last auction` : ''}
            {r.origin === 'discovery' && r.holders ? ` · held by ${r.holders} winning firm${r.holders > 1 ? 's' : ''}` : r.origin === 'market' ? ` · market scan · cleared in ${r.holders ?? '?'} auctions` : ''}
          </div>
          {r.overbidNote && <div className="mt-1 text-[11px] text-amber-400">{r.overbidNote}</div>}
          {r.flag && <div className="mt-1 text-[11px] text-zinc-500">{r.flag}</div>}
        </td>
        <td className="px-2 py-2.5 text-right align-top">
          {(() => {
            const ev = evOf(r)
            if (ev === null) return <span className="text-[12px] text-zinc-600">—</span>
            const conf = (r.cleared !== null ? 1 : 0) + (r.flag ? 0 : 1)
              + (r.origin !== 'market' ? 1 : 0) + (r.pctHours !== null ? 1 : 0)
            const win = r.pctHours !== null ? Math.round(r.pctHours > 1 ? r.pctHours : r.pctHours * 100) : null
            const px = r.cleared ?? r.ceiling
            const edgeMw = Math.round((r.worth - px) * d.hours)
            return (
              <div className="relative">
                <div className="absolute inset-y-0 right-0 rounded-sm"
                  style={{ width: `${Math.min(Math.abs(ev), 100)}%`,
                           background: ev >= 0 ? 'rgba(52,211,153,0.12)' : 'rgba(244,63,94,0.12)' }} />
                <div className={`tnum relative text-[17px] font-bold ${ev >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {ev >= 0 ? '+' : ''}{ev}%
                </div>
                <div className="relative mt-0.5 text-[10px] text-zinc-500">
                  Top {evRank[r.key] ?? '—'}%{win !== null ? ` · pays ${win}% of hrs` : ''}
                  {edgeMw !== 0 ? ` · ${edgeMw > 0 ? '+' : ''}$${Math.abs(edgeMw) >= 1000 ? `${(edgeMw / 1000).toFixed(1)}k` : edgeMw}/MW` : ''}
                </div>
                <div className="relative mt-0.5 text-[9px] tracking-widest text-zinc-600" title="confidence: clearing history, no flags, verified origin, payoff data">
                  {'●'.repeat(conf)}{'○'.repeat(4 - conf)}
                </div>
              </div>
            )
          })()}
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
            {r.prevMw
              ? `you held ${r.prevMw.toFixed(0)}`
              : r.maxMw
                ? `auction max ~${r.maxMw.toFixed(0)} MW`
                : 'new path'}
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
          {r.hedge === 'OBL' && (
            <div className="text-[10px] text-amber-400/80">OBL — can lose more</div>
          )}
        </td>
      </tr>
    )
  }

  const Head = () => (
    <thead>
      <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-zinc-500">
        <th className="w-8 px-2 py-2" />
        <th className="px-2 py-2 font-medium">Path</th>
        <th className="px-2 py-2 text-right font-medium">Edge<br /><span className="normal-case text-zinc-600">return per $1 paid, at its usual clearing price · dots = data coverage</span></th>
        <th className="px-2 py-2 text-right font-medium">Your limit<br /><span className="normal-case text-zinc-600">$/MWh — not what you pay</span></th>
        <th className="px-2 py-2 text-right font-medium">MW</th>
        <th className="px-2 py-2 text-right font-medium">Likely cost<br /><span className="normal-case text-zinc-600">at its going rate</span></th>
        <th className="px-2 py-2 text-right font-medium">Typical month&apos;s return<br /><span className="normal-case text-zinc-600">delivery-month-capped history</span></th>
        <th className="px-2 py-2 text-right font-medium">Cost at your limit<br /><span className="normal-case text-zinc-600">if it clears at your full bid</span></th>
      </tr>
    </thead>
  )

  // Shortlist: an explicit member action, never a default. Market-scan rows
  // stay unverified by rule (July holdout), so the sheet does not pre-select
  // them; this ticks the top rows of the current view in the sheet's own
  // order (liquidity first, then edge). Values are untouched.
  function selectTop() {
    const pool = rows.filter((r) => hedgeLens !== 'selected' && lens(r)).sort(byEv).slice(0, SHORTLIST_N)
    setChecked((c) => ({ ...c, ...Object.fromEntries(pool.map((r) => [r.key, true])) }))
  }
  const clearAll = () => setChecked(Object.fromEntries(rows.map((r) => [r.key, false])))

  const ex = green[0] ?? amber[0]
  const fileRows = [...selected].sort(byEv)

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
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">cost at your limits</div>
            <div className="tnum text-[15px] font-semibold text-zinc-400">{money(totals.maxCost)}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {auction.holderOptions.length > 1 ? (
              <select value={holder} onChange={(e) => setHolder(e.target.value)}
                aria-label="CRR account for the bid file"
                className="rounded border border-line bg-ink px-2 py-1.5 font-mono text-[12px] text-zinc-200">
                {auction.holderOptions.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            ) : auction.holderOptions.length === 0 ? (
              <input value={holder} onChange={(e) => setHolder(e.target.value.toUpperCase().trim())}
                placeholder="YOUR CRR CODE" aria-label="Your ERCOT CRR account code"
                className={`w-32 rounded border bg-ink px-2 py-1.5 font-mono text-[12px] text-zinc-200 outline-none ${holder && !holderOk ? 'border-amber-500' : 'border-line focus:border-emerald-500'}`} />
            ) : null}
            <button
              onClick={downloadCsv}
              disabled={selected.length === 0 || !holderOk}
              title={!holderOk ? 'Enter your CRR account code — ERCOT needs it on every row' : undefined}
              className="rounded-md bg-emerald-600 px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-40"
            >
              Download bid file ({selected.length})
            </button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-600">
          <button onClick={() => setShowFile((v) => !v)} disabled={selected.length === 0}
            className="text-zinc-300 hover:text-white disabled:text-zinc-600">
            {showFile ? '▾' : '▸'} In this file ({selected.length})
          </button>
          {hiddenSelected > 0 && (
            <button onClick={() => { setHedgeLens('selected'); setSearch('') }} className="text-amber-400 hover:text-amber-300">
              {hiddenSelected} selected not shown in this view — show them
            </button>
          )}
          {!holderOk && (
            <span className="text-amber-400">
              {holder ? `"${holder}" doesn't look like a CRR account code` : 'Enter your CRR account code to download'}
            </span>
          )}
          {restored && <span>draft restored from this browser ·</span>}
          <button onClick={resetDraft} className="hover:text-zinc-300">reset to defaults</button>
        </div>
        {showFile && selected.length > 0 && (
          <div className="mt-2 max-h-56 overflow-y-auto rounded border border-line bg-ink/60">
            <table className="w-full border-collapse text-[11.5px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="px-2 py-1 font-medium">Path</th>
                  <th className="px-2 py-1 font-medium">Block · type</th>
                  <th className="px-2 py-1 text-right font-medium">MW</th>
                  <th className="px-2 py-1 text-right font-medium">Limit</th>
                  <th className="px-2 py-1 text-right font-medium">Cost at limit</th>
                </tr>
              </thead>
              <tbody>
                {fileRows.map((r) => (
                  <tr key={r.key} className="border-t border-line/50 text-zinc-300">
                    <td className="px-2 py-1">{r.source} → {r.sink}</td>
                    <td className="px-2 py-1 text-zinc-500">{r.tou} · {r.hedge}</td>
                    <td className="px-2 py-1 text-right tnum">{qty[r.key]}</td>
                    <td className="px-2 py-1 text-right tnum">{usd(r.ceiling)}</td>
                    <td className="px-2 py-1 text-right tnum">{money(derived[r.key].maxCost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-zinc-600">
          CSV matches ERCOT&apos;s CRR upload format · account {holder || '—'} · delivery{' '}
          {auction.deliveryLabel} · cost at your limits is what you pay only if every path clears
          at your full bid — the historical norm is the likely column. On OPT rows the premium is
          the most you can lose; OBL rows can cost more than it in bad months.
        </p>
      </div>

      {ex && (() => {
        const eh = auction.hours[ex.tou] ?? 0
        const eq = ex.suggestedMw
        return (
          <details className="rounded-lg border border-line bg-panel px-4 py-3 text-[12.5px] text-zinc-400">
            <summary className="cursor-pointer select-none font-semibold text-zinc-200">
              How to read a row, using the first one
            </summary>
            <p className="mt-2">
              A CRR here is a block of {eh} {ex.tou} hours in {monthLong}. {eq} MW means you are
              buying {eq} × {eh} = {(eq * eh).toLocaleString()} MWh. Your limit of {usd(ex.ceiling)}
              /MWh is the most you authorise — <span className="text-zinc-200">everyone pays the
              same clearing price, not their bid</span>, and this path has recently cleared
              around {ex.cleared !== null ? usd(ex.cleared) : 'unknown'}, so you would likely pay
              about {money(eq * eh * (ex.cleared ?? ex.ceiling))} in total. If it clears exactly
              at your limit, the cost is {money(eq * eh * ex.ceiling)}
              {ex.hedge === 'OBL' ? ' — and as an obligation it can lose more than that in a bad month' : ''}.
              A lower limit does not reduce what a winner pays — it only lowers the odds of filling.
            </p>
          </details>
        )
      })()}

      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="text-zinc-500">Show:</span>
        {(['both', 'OPT', 'OBL', 'selected'] as const).map((h) => (
          <button key={h} onClick={() => setHedgeLens(h)}
            className="rounded px-2 py-0.5"
            style={{ background: hedgeLens === h ? '#24404b' : 'transparent',
                     color: hedgeLens === h ? '#f2f6f6' : '#7d9096' }}>
            {h === 'both' ? 'All' : h === 'OPT' ? 'Options' : h === 'OBL' ? 'Obligations' : `Selected (${selected.length})`}
          </button>
        ))}
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="search node…" aria-label="Filter paths by source or sink"
          className="ml-2 w-40 rounded border border-line bg-transparent px-2 py-0.5 text-[11px] text-zinc-200 outline-none focus:border-emerald-500" />
        <span className="ml-auto flex items-center gap-3">
          {hedgeLens !== 'selected' && (
            <button onClick={selectTop} className="rounded border border-line px-2 py-0.5 text-zinc-300 hover:text-white">
              Select top {SHORTLIST_N} in this view
            </button>
          )}
          <button onClick={clearAll} disabled={selected.length === 0} className="text-zinc-500 hover:text-zinc-300 disabled:opacity-40">
            Clear selection
          </button>
        </span>
        {hedgeLens === 'OBL' && (
          <span className="basis-full text-amber-400/80">
            obligations pay both directions — the class returned +22% over 17 scored months, but a single inverted month collects from you
          </span>
        )}
      </div>

      {!ex && (
        <p className="rounded-lg border border-line bg-panel px-4 py-6 text-center text-[12.5px] text-zinc-500">
          {hedgeLens === 'selected'
            ? 'Nothing selected yet.'
            : needle
              ? `No path on this sheet touches “${search.trim()}”.`
              : hedgeLens === 'OBL' ? 'No obligations on this sheet.' : 'No options on this sheet.'}
        </p>
      )}

      {green.length === 0 && amber.length > 0 && hedgeLens === 'both' && !needle && (
        <div className="rounded-lg border border-line bg-panel px-4 py-3 text-[12.5px] text-zinc-400">
          <span className="font-semibold text-zinc-200">No verified rows on your sheet this month. </span>
          Market-scan rows are never marked verified until a bid on them has been validated end
          to end, so nothing is pre-selected. Rows below are ranked by liquidity, then edge — use{' '}
          <button onClick={selectTop} className="text-emerald-400 hover:text-emerald-300">
            Select top {SHORTLIST_N}
          </button>{' '}
          to start a draft from the top of that list, then trim it.
        </div>
      )}

      {green.length > 0 && (
        <section>
          <div className="mb-1 flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold text-zinc-200">Verified value</h2>
            <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
              full limit supported
            </span>
          </div>
          <p className="mb-3 max-w-[70ch] text-[12.5px] text-zinc-500">
            Worth more than the auction has charged, on real clearing history. The green figure
            is the most our margin rule supports, not an instruction — the auction charges
            everyone the same clearing price, not their bid, so a limit at the full ceiling adds
            wins without adding cost.
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full min-w-[980px] border-collapse"><Head /><tbody>
              {green.map(renderRow)}
            </tbody></table>
          </div>
        </section>
      )}

      {amber.length > 0 && (
        <section>
          <div className="mb-1 flex items-baseline gap-2">
            <h2 className="text-[15px] font-semibold text-zinc-200">Unverified or flagged</h2>
            <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
              unverified — size small
            </span>
            <span className="text-[11px] text-zinc-600">{amber.length} rows</span>
          </div>
          <p className="mb-3 max-w-[70ch] text-[12.5px] text-zinc-500">
            Positive value on paper, but either the path has never been seen clearing an auction —
            so the &ldquo;cheap&rdquo; cannot be verified — or a caution applies. Unchecked by
            default; deliberately small suggested sizes.
          </p>
          <div className="overflow-x-auto rounded-lg border border-line bg-panel">
            <table className="w-full min-w-[980px] border-collapse"><Head /><tbody>
              {amber.map(renderRow)}
            </tbody></table>
          </div>
        </section>
      )}
      <p className="text-[10.5px] leading-relaxed text-zinc-600">
        Honesty note: Edge and the typical month&apos;s return use the scan&apos;s
        month-honest base — the median of per-month payouts, capped by what that actual delivery month
        paid in past years and by the recent three months — because the raw annual average overstates a
        single month badly on spike-driven paths (our own holdout put it near 10×). Treat them
        as ranking signals, not forecasts. Edge is rounded to 5-point steps on purpose — our
        magnitude estimates land within 2× of realized on ~61% of positions, so decimals would
        overstate precision. The
        96%+ out-of-sample sign accuracy we cite belongs to the constraint-exposure model (does
        a constraint move this path&apos;s basis the way we say) — sheet-level pick accuracy is a
        different question, and it is scored publicly on the Track record as each sheet&apos;s
        auction posts and its delivery month settles. Dots under Edge count data coverage (clearing history, no flags, verified
        origin, payoff data) — they are not a probability. On OBL rows the cost at your limit is NOT
        the most you can lose: an obligation settles both directions with no floor.
      </p>
      <p className="text-[10.5px] leading-relaxed text-zinc-600">
        HYPOTHETICAL PERFORMANCE DISCLOSURE: Shadowprice&apos;s self-scored results are
        hypothetical — no actual bids were submitted and no positions were held. Hypothetical
        results have inherent limitations: they do not reflect actual market participation
        (fills are assumed at posted clearing prices, capped at awarded volume), and no
        representation is made that any account will or is likely to achieve similar results.
        All figures on this sheet are historical description, not a forecast or a
        recommendation.
      </p>
    </div>
  )
}
