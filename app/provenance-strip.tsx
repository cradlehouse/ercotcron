'use client'
// The provenance strip (UI review #1): run identity wherever a number
// appears. Every figure on the page traces to a computation the reader can
// name — computed-at, history window, data-through, sheet freeze, and the
// marks run id / engine SHA once mark_runs is populated.
import { useEffect, useState } from 'react'
import { rpc } from '@/lib/rpc'

type Prov = {
  valuations: { computed_at: string | null; window_start: string | null; window_end: string | null; rows: number } | null
  sheets: { sheet: string; frozen_at: string; rows: number }[]
  data_through: string | null
  mark_run: { run_id: string; run_at: string; engine_sha: string; methodology_v: string } | null
}

const d10 = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '—')

export function ProvenanceStrip({ sheet }: { sheet?: string }) {
  const [prov, setProv] = useState<Prov | null>(null)
  useEffect(() => {
    rpc<Prov>('get_provenance').then(({ data }) => data && setProv(data))
  }, [])
  if (!prov) return null
  const sh = sheet ? prov.sheets.find(s => s.sheet === sheet) : null
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-line/60 pt-1.5 font-mono text-[11px] text-[#7d9096]">
      {sh && <span>sheet frozen {sh.frozen_at.slice(0, 16).replace('T', ' ')} UTC · {sh.rows} rows</span>}
      {prov.valuations?.computed_at && (
        <span>valuations {d10(prov.valuations.computed_at)} · history {d10(prov.valuations.window_start)} → {d10(prov.valuations.window_end)}</span>
      )}
      <span>settled prices through {d10(prov.data_through)}</span>
      {prov.mark_run
        ? <span>run {prov.mark_run.run_id} · engine {prov.mark_run.engine_sha.slice(0, 8)} · methodology {prov.mark_run.methodology_v}</span>
        : <span>methodology v1.2</span>}
    </div>
  )
}
