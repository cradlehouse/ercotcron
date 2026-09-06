'use client'
// The method, judged — one sheet at a time.
// Verdict first: three camp tiles (won / outbid / refused) with money; the
// month as a flow field (click a tile to isolate a camp and see its group
// daily over/under); then evidence tables in descending interest, with
// never-traded collapsed. Paper batches (real stored bids) get their own tab.
import { Fragment, useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'
import { DailyChart, type DailyRow } from '../../daily-chart'
import { SheetFlowChart, type ClassKey } from './sheet-flow'

type Prog = { grp: string; source: string; sink: string; tou: string; hedge: string; tier: string; bid: number | null; clearing: number | null; mw: number; delivery: string; status: string; hours: number; cost: number | null; paid: number | null }

const usd = (v: number) => `$${Math.abs(v).toLocaleString()}`
const signed = (v: number) => `${v >= 0 ? '+' : '−'}${usd(v)}`

function campOf(r: Prog): 'won' | 'outbid' | 'refused' | 'ghost' {
  if (r.tier === 'red') return 'refused'
  if (r.status === 'never traded') return 'ghost'
  if (r.status.startsWith('missed')) return 'outbid'
  return 'won'
}
const CAMP_META = {
  won: { title: 'Won', blurb: 'we said bid — our limit would have filled', color: '#34d399', chart: 'ours' as ClassKey },
  outbid: { title: 'Outbid', blurb: 'we said bid — the market paid more than our discipline allows', color: '#f87171', chart: 'market' as ClassKey },
  refused: { title: 'Said no', blurb: "the red list, tracked at the market's price", color: '#c07b5a', chart: 'reds' as ClassKey },
}

export default function MethodScore() {
  const [prog, setProg] = useState<Prog[] | null>(null)
  const [state, setState] = useState<'loading' | 'member' | 'admin'>('loading')
  const [tab, setTab] = useState<string | null>(null)
  const [camp, setCamp] = useState<ClassKey | null>(null)
  const [openRow, setOpenRow] = useState<string | null>(null)
  const [daily, setDaily] = useState<Record<string, DailyRow[] | 'loading'>>({})
  const [showGhosts, setShowGhosts] = useState(false)

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      const { data: pr } = await sb.rpc('get_method_progress')
      if (Array.isArray(pr) && pr.length > 0) { setProg(pr as Prog[]); setState('admin') } else setState('member')
    })
  }, [])

  async function toggleRow(r: Prog) {
    const key = `${r.grp}|${r.source}|${r.sink}|${r.tou}|${r.hedge}`
    if (openRow === key) { setOpenRow(null); return }
    setOpenRow(key)
    if (!daily[key]) {
      setDaily(d => ({ ...d, [key]: 'loading' }))
      const { data } = await sb.rpc('get_path_daily', {
        p_src: r.source, p_snk: r.sink, p_tou: r.tou, p_hedge: r.hedge,
        p_month: `${r.delivery}-01`,
      })
      const rows = ((data as { d: string; hours: number; paid_per_mwh: number }[]) ?? []).map(x => ({
        d: x.d, hours: x.hours,
        paid_in: Math.round((r.clearing ?? 0) * x.hours * r.mw),
        paid_out: Math.round(x.paid_per_mwh * r.mw),
      }))
      setDaily(d => ({ ...d, [key]: rows }))
    }
  }

  if (state === 'loading') return <div className="p-6 text-sm text-[#7d9096]">loading…</div>
  if (state === 'member' || !prog) return (
    <div className="p-6 text-sm text-[#93a6ab]">
      Sheet scores publish to the <a href="/app/record" className="text-[#eda63a]">Track record</a> page
      as each auction and settlement completes.
    </div>
  )

  const sheets = [...new Set(prog.filter(p => !p.grp.startsWith('paper:')).map(p => p.grp))]
  const papers = [...new Set(prog.filter(p => p.grp.startsWith('paper:')).map(p => p.grp))]
  const active = tab ?? sheets[0] ?? papers[0]
  const isPaper = active?.startsWith('paper:') || active === '__papers__'
  const rows = prog.filter(p => p.grp === active)

  const camps = {
    won: rows.filter(r => campOf(r) === 'won'),
    outbid: rows.filter(r => campOf(r) === 'outbid'),
    refused: rows.filter(r => campOf(r) === 'refused' && r.clearing !== null),
    ghost: rows.filter(r => campOf(r) === 'ghost'),
  }
  const sums = (rs: Prog[]) => {
    const live = rs.filter(r => r.hours > 0)
    const cost = live.reduce((a, r) => a + (r.cost ?? 0), 0)
    const paid = live.reduce((a, r) => a + (r.paid ?? 0), 0)
    return { cost, paid, net: paid - cost }
  }

  const RowLine = ({ r }: { r: Prog }) => {
    const key = `${r.grp}|${r.source}|${r.sink}|${r.tou}|${r.hedge}`
    const canOpen = r.hours > 0
    const isOpen = openRow === key
    const dd = daily[key]
    return (
      <Fragment>
        <tr onClick={() => canOpen && toggleRow(r)}
            className={`border-b border-line/40 text-[#93a6ab] last:border-0 ${canOpen ? 'cursor-pointer hover:bg-panel-2/40' : ''} ${isOpen ? 'bg-panel-2/30' : ''}`}>
          <td className="px-2 py-1 font-mono text-[11.5px] text-[#dbe4e6]">
            {canOpen && <span className="mr-1 text-[10px] text-[#eda63a]">{isOpen ? '▾' : '▸'}</span>}
            {r.source} → {r.sink}
            <a className="ml-2 text-[#eda63a] hover:text-[#f5b95c]" title="dossier"
               onClick={e => e.stopPropagation()}
               href={`/path?src=${encodeURIComponent(r.source)}&snk=${encodeURIComponent(r.sink)}`}>↗</a>
          </td>
          <td className="px-2 py-1">{r.tou} · {r.hedge}</td>
          <td className="px-2 py-1 text-right tnum">{r.bid !== null ? `$${Number(r.bid).toFixed(2)}` : '—'}</td>
          <td className="px-2 py-1 text-right tnum">{r.clearing !== null ? `$${Number(r.clearing).toFixed(4)}` : '—'}</td>
          <td className="px-2 py-1 text-right tnum">{Number(r.mw)} MW</td>
          <td className="px-2 py-1 text-right tnum">{r.cost !== null && r.hours > 0
            ? (r.cost < 0 ? <span className="text-emerald-400/80">collected {usd(r.cost)}</span> : `${usd(r.cost)} in`)
            : (r.status === 'awaiting results' || r.status === 'awaiting delivery') ? r.status : ''}</td>
          <td className={`px-2 py-1 text-right tnum ${r.paid !== null && r.paid < 0 ? 'text-red-400/80' : ''}`}>
            {r.paid !== null && r.hours > 0 ? `${r.paid < 0 ? '−' : ''}${usd(r.paid)} out` : ''}</td>
          <td className={`px-2 py-1 text-right tnum ${r.paid !== null && r.cost !== null && r.hours > 0 ? ((r.paid - r.cost) >= 0 ? 'text-emerald-400' : 'text-red-400') : ''}`}>
            {r.paid !== null && r.cost !== null && r.hours > 0 ? signed(r.paid - r.cost) : ''}</td>
        </tr>
        {isOpen && (
          <tr className="border-b border-line/40">
            <td colSpan={8} className="bg-ink/40 px-3 py-3">
              {dd === 'loading' || !dd
                ? <div className="text-[12px] text-[#7d9096]">pulling the daily record…</div>
                : dd.length === 0
                  ? <div className="text-[12px] text-[#93a6ab]">No settled days yet.</div>
                  : <DailyChart rows={dd} month={r.delivery} />}
            </td>
          </tr>
        )}
      </Fragment>
    )
  }

  const Table = ({ rs }: { rs: Prog[] }) => (
    <div className="mt-2 overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full min-w-[880px] border-collapse text-[12px]">
        <thead>
          <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
            <th className="px-2 py-1.5">Path</th><th className="px-2 py-1.5">Block · type</th>
            <th className="px-2 py-1.5 text-right">Our limit</th><th className="px-2 py-1.5 text-right">Cleared</th>
            <th className="px-2 py-1.5 text-right">MW</th><th className="px-2 py-1.5 text-right">Cost</th>
            <th className="px-2 py-1.5 text-right">Paid out</th><th className="px-2 py-1.5 text-right">Net</th>
          </tr>
        </thead>
        <tbody>{rs.map((r, i) => <RowLine key={i} r={r} />)}</tbody>
      </table>
    </div>
  )

  return (
    <div className="mx-auto max-w-6xl p-4 text-[#f2f6f6]">
      <h1 className="text-[15px] font-semibold">Method score</h1>
      <p className="mt-1 text-[12.5px] text-[#7d9096]">
        One sheet at a time, judged three ways. Hypothetical — no bids submitted, no positions
        held; results do not reflect actual market participation and predict nothing.
      </p>

      <div className="mt-4 flex flex-wrap gap-2 text-[12.5px]">
        {sheets.map(s => (
          <button key={s} onClick={() => { setTab(s); setCamp(null); setOpenRow(null) }}
            className={`rounded px-2.5 py-1 ${active === s ? 'bg-panel-2 text-[#f2f6f6]' : 'text-[#7d9096] hover:text-[#dbe4e6]'}`}>
            {s.replace('2026Monthly', ' 2026 monthly').replace('-reconstructed', ' (reconstructed)')}
          </button>
        ))}
        {papers.length > 0 && (
          <button onClick={() => { setTab('__papers__'); setCamp(null); setOpenRow(null) }}
            className={`rounded px-2.5 py-1 ${isPaper ? 'bg-panel-2 text-[#f2f6f6]' : 'text-[#7d9096] hover:text-[#dbe4e6]'}`}>
            Paper batches
          </button>
        )}
      </div>

      {isPaper ? (
        <div className="mt-2">
          {papers.map(pb => (
            <div key={pb} className="mt-5">
              <div className="text-[13.5px] font-medium text-[#dbe4e6]">{pb.replace('paper: ', '')}</div>
              <Table rs={prog.filter(p => p.grp === pb)} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {(['won', 'outbid', 'refused'] as const).map(k => {
              const meta = CAMP_META[k]
              const rs = camps[k]
              const { cost, paid, net } = sums(rs)
              const sel = camp === meta.chart
              return (
                <button key={k} onClick={() => setCamp(sel ? null : meta.chart)}
                  className={`rounded-lg border p-3 text-left transition-colors ${sel ? 'border-[#eda63a] bg-panel-2/50' : 'border-line bg-panel/50 hover:bg-panel-2/30'}`}>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[15px] font-semibold" style={{ color: meta.color }}>{meta.title}</span>
                    <span className="text-[12px] text-[#7d9096]">{rs.length} paths</span>
                  </div>
                  <div className="mt-1 text-[12px] text-[#7d9096]">{meta.blurb}</div>
                  {(cost !== 0 || paid !== 0) ? (
                    <div className="mt-2 text-[13.5px] text-[#dbe4e6]">
                      {cost < 0 ? `collected ${usd(cost)}` : `${usd(cost)} in`} → {paid < 0 ? '−' : ''}{usd(paid)} out ·{' '}
                      <span className={net >= 0 ? 'text-emerald-400' : 'text-red-400'}>{signed(net)} net</span>
                      {cost > 0 && <span className="text-[#7d9096]"> · {Math.round((paid / cost) * 100)}%</span>}
                    </div>
                  ) : <div className="mt-2 text-[13.5px] text-[#61767e]">no settled days yet</div>}
                  <div className="mt-1 text-[11px] text-[#61767e]">{sel ? 'isolated on the chart — click to clear' : 'click to isolate + see group daily bars'}</div>
                </button>
              )
            })}
          </div>
          {camps.ghost.length > 0 && (
            <p className="mt-2 text-[12px] text-[#61767e]">
              Plus {camps.ghost.length} recommended paths that never traded at all — the liquidity
              reality the gates exist for.
            </p>
          )}

          <SheetFlowChart sheet={active} camp={camp} />

          <h2 className="mt-8 text-[14px] font-medium" style={{ color: CAMP_META.won.color }}>Won — {camps.won.length}</h2>
          <Table rs={camps.won} />
          <h2 className="mt-8 text-[14px] font-medium" style={{ color: CAMP_META.outbid.color }}>Outbid — {camps.outbid.length}</h2>
          <Table rs={camps.outbid} />
          <h2 className="mt-8 text-[14px] font-medium" style={{ color: CAMP_META.refused.color }}>Said no (traded) — {camps.refused.length}</h2>
          <Table rs={camps.refused} />
          {camps.ghost.length > 0 && (
            <div className="mt-8 pb-8">
              <button onClick={() => setShowGhosts(g => !g)} className="text-[13px] text-[#7d9096] hover:text-[#dbe4e6]">
                {showGhosts ? '▾' : '▸'} Never traded — {camps.ghost.length} (least interesting, but on the record)
              </button>
              {showGhosts && <Table rs={camps.ghost} />}
            </div>
          )}
        </>
      )}
    </div>
  )
}
