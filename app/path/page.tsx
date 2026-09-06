'use client'
// The path dossier: everything the platform knows about one path, one page.
// Descriptive only — identical for every member. Linked from the chart, the
// map, and the bid sheet.
import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { sb } from '@/lib/supabase'

type Award = { auction: string; tou: string; hedge: string; cp: number; mw: number; holders: number; start: string; end: string }
type Payoff = { m: string; tou: string; obl: number; opt: number; hours: number }
type Offer = { auction: string; tou: string; hedge: string; mw: number; min_ask: number }
type Valuation = { book: string; time_of_use: string; hedge_type: string; value_mean: number | string | null; value_typical: number | string | null; ceiling: number | string | null; cleared_price: number | string | null; warnings: string | null; window_end: string | null }
type Paper = { batch: string; auction: string; tou: string; hedge: string; mw: number; bid: number; cleared: boolean | null; cp: number | null; pnl: number | null }
type Dossier = { awards: Award[]; payoffs: Payoff[]; offers: Offer[]; valuations: Valuation[]; paper: Paper[] }

const n = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined ? null : Number(v)
const usd = (v: number | null, dp = 2) => (v === null ? '—' : `$${v.toFixed(dp)}`)

function Dossier() {
  const params = useSearchParams()
  const src = params.get('src') ?? ''
  const snk = params.get('snk') ?? ''
  const [d, setD] = useState<Dossier | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!src || !snk) return
    sb.rpc('get_path_dossier', { p_src: src, p_snk: snk }).then(({ data, error }) => {
      if (error) setError(error.message)
      else setD(data as Dossier)
    })
  }, [src, snk])

  if (!src || !snk) return <div className="p-6 text-sm text-[#93a6ab]">No path given — open a dossier from the map, the chart, or a bid sheet.</div>
  if (error) return <div className="p-6 text-sm text-red-400">{error}</div>
  if (!d) return <div className="p-6 text-sm text-[#7d9096]">pulling the record for {src} → {snk}…</div>

  const monthly = d.awards.filter(a => a.auction.endsWith('Monthly'))
  const longterm = d.awards.filter(a => !a.auction.endsWith('Monthly'))
  const payByMonth = new Map<string, Payoff[]>()
  for (const p of d.payoffs) {
    if (!payByMonth.has(p.m)) payByMonth.set(p.m, [])
    payByMonth.get(p.m)!.push(p)
  }
  // price trend across monthly auctions, per TOU·hedge with the most MW
  const first = monthly[0], last = monthly[monthly.length - 1]

  return (
    <div className="mx-auto max-w-5xl px-2 py-2 text-[#f2f6f6]">
      <h1 className="text-lg font-medium">{src} <span className="text-[#61767e]">→</span> {snk}</h1>
      <p className="mt-1 text-[13px] text-[#93a6ab]">
        The path&apos;s public record: what every auction charged, what delivery actually paid,
        who has tried to sell out, and our published reference. Identical for every member —
        description, not a recommendation.
      </p>

      <section className="mt-6 rounded border border-line bg-panel/50 p-4">
        <h2 className="text-[14px] font-medium">What auctions charged for it</h2>
        {d.awards.length === 0 ? (
          <p className="mt-1 text-[13px] text-[#93a6ab]">Never cleared in any auction we hold.</p>
        ) : (
          <>
            {first && last && first !== last && (
              <p className="mt-1 text-[13px] text-[#93a6ab]">
                Monthly clearing moved {usd(first.cp, 4)} ({first.auction}) →{' '}
                {usd(last.cp, 4)} ({last.auction}):{' '}
                <span className={last.cp >= first.cp ? 'text-[#f2c14e]' : 'text-emerald-400'}>
                  {last.cp >= first.cp
                    ? `▲ ${first.cp > 0 ? Math.round(((last.cp - first.cp) / first.cp) * 100) : '∞'}% pricier`
                    : `▼ ${Math.round(((first.cp - last.cp) / Math.max(first.cp, 1e-9)) * 100)}% cheaper`}
                </span>
              </p>
            )}
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-[12.5px]">
                <thead>
                  <tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wider text-[#61767e]">
                    <th className="px-2 py-1.5 font-medium">Auction</th>
                    <th className="px-2 py-1.5 font-medium">Block · type</th>
                    <th className="px-2 py-1.5 text-right font-medium">Cleared at</th>
                    <th className="px-2 py-1.5 text-right font-medium">MW traded</th>
                    <th className="px-2 py-1.5 text-right font-medium">Winning firms</th>
                    <th className="px-2 py-1.5 text-right font-medium">Delivery</th>
                  </tr>
                </thead>
                <tbody>
                  {[...monthly, ...longterm].map((a, i) => (
                    <tr key={i} className="border-b border-line/50 text-[#93a6ab] last:border-0">
                      <td className="px-2 py-1.5 text-[#dbe4e6]">{a.auction}</td>
                      <td className="px-2 py-1.5">{a.tou} · {a.hedge}</td>
                      <td className="px-2 py-1.5 text-right tnum">{usd(a.cp, 4)}</td>
                      <td className="px-2 py-1.5 text-right tnum">{a.mw}</td>
                      <td className="px-2 py-1.5 text-right tnum">{a.holders}</td>
                      <td className="px-2 py-1.5 text-right">{a.start?.slice(0, 7)}{a.end && a.end.slice(0, 7) !== a.start?.slice(0, 7) ? `–${a.end.slice(0, 7)}` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="mt-5 rounded border border-line bg-panel/50 p-4">
        <h2 className="text-[14px] font-medium">What delivery actually paid</h2>
        <p className="mt-1 text-[12.5px] text-[#61767e]">
          Average payout per MWh-hour, by month and hour block, from settled day-ahead prices.
          &ldquo;As option&rdquo; floors bad hours at zero; &ldquo;as obligation&rdquo; keeps both directions.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wider text-[#61767e]">
                <th className="px-2 py-1.5 font-medium">Month</th>
                <th className="px-2 py-1.5 font-medium">Block</th>
                <th className="px-2 py-1.5 text-right font-medium">As option ($/MWh)</th>
                <th className="px-2 py-1.5 text-right font-medium">As obligation ($/MWh)</th>
                <th className="px-2 py-1.5 text-right font-medium">Hours</th>
              </tr>
            </thead>
            <tbody>
              {d.payoffs.slice(-24).map((p, i) => (
                <tr key={i} className="border-b border-line/50 text-[#93a6ab] last:border-0">
                  <td className="px-2 py-1.5 text-[#dbe4e6]">{p.m}</td>
                  <td className="px-2 py-1.5">{p.tou}</td>
                  <td className="px-2 py-1.5 text-right tnum">{usd(p.opt, 4)}</td>
                  <td className={`px-2 py-1.5 text-right tnum ${p.obl < 0 ? 'text-red-400' : ''}`}>{usd(p.obl, 4)}</td>
                  <td className="px-2 py-1.5 text-right tnum">{p.hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="mt-5 grid gap-5 md:grid-cols-2">
        <section className="rounded border border-line bg-panel/50 p-4">
          <h2 className="text-[14px] font-medium">The sell side</h2>
          {d.offers.length === 0 ? (
            <p className="mt-1 text-[13px] text-[#93a6ab]">No holder has offered this path for sale in the auctions we hold.</p>
          ) : (
            <table className="mt-2 w-full border-collapse text-[12.5px]">
              <thead>
                <tr className="border-b border-line text-left text-[10.5px] uppercase tracking-wider text-[#61767e]">
                  <th className="py-1.5 pr-2 font-medium">Auction</th>
                  <th className="py-1.5 pr-2 font-medium">Block · type</th>
                  <th className="py-1.5 text-right font-medium">MW offered</th>
                  <th className="py-1.5 text-right font-medium">Lowest ask</th>
                </tr>
              </thead>
              <tbody>
                {d.offers.map((o, i) => (
                  <tr key={i} className="border-b border-line/50 text-[#93a6ab] last:border-0">
                    <td className="py-1.5 pr-2 text-[#dbe4e6]">{o.auction}</td>
                    <td className="py-1.5 pr-2">{o.tou} · {o.hedge}</td>
                    <td className="py-1.5 text-right tnum">{o.mw}</td>
                    <td className="py-1.5 text-right tnum">{usd(o.min_ask, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="rounded border border-line bg-panel/50 p-4">
          <h2 className="text-[14px] font-medium">Our published reference</h2>
          {d.valuations.length === 0 ? (
            <p className="mt-1 text-[13px] text-[#93a6ab]">Not on the current bid sheet — it didn&apos;t pass the margin and liquidity gates.</p>
          ) : d.valuations.map((v, i) => (
            <div key={i} className="mt-2 border-b border-line/50 pb-2 text-[13px] text-[#93a6ab] last:border-0">
              <div className="text-[#dbe4e6]">{v.time_of_use} · {v.hedge_type}</div>
              <div className="mt-0.5">
                reference limit {usd(n(v.ceiling))} · typical month {usd(n(v.value_typical) ?? n(v.value_mean))}/MWh ·
                usually clears {usd(n(v.cleared_price))}
              </div>
              {v.warnings && <div className="mt-0.5 text-amber-400/80">{v.warnings}</div>}
            </div>
          ))}
          {d.paper.length > 0 && (
            <div className="mt-3 text-[12.5px] text-[#93a6ab]">
              <div className="text-[11px] uppercase tracking-wider text-[#61767e]">On the model&apos;s record</div>
              {d.paper.map((p, i) => (
                <div key={i} className="mt-1">
                  {p.auction}: {p.mw} MW at {usd(p.bid)} —{' '}
                  {p.cleared === null ? 'awaiting results' : p.cleared
                    ? <span className="text-emerald-400">filled at {usd(p.cp, 4)}</span>
                    : <span className="text-[#61767e]">missed</span>}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <p className="mt-6 max-w-[90ch] text-[10.5px] leading-relaxed text-[#61767e]">
        All figures derive from public ERCOT data; hour-block classification follows our
        published methodology (its stated holiday edge cases apply). Historical description,
        not a forecast or a recommendation. Reference limits are what our margin rule
        supports, identical for every member.
      </p>
    </div>
  )
}

export default function PathPage() {
  return <Suspense fallback={<div className="p-6 text-sm text-[#7d9096]">loading…</div>}><Dossier /></Suspense>
}
