'use client'
// Shared daily win/loss chart: bars on settled days (net = paid out − cost),
// the rest of the delivery month laid out empty, cumulative net line on top.
// Used by My book's running positions and the method progress screen.

export type DailyRow = { d: string; hours: number; paid_in: number; paid_out: number }

export function DailyChart({ rows, month }: { rows: DailyRow[]; month?: string }) {
  const ref = month ? new Date(`${month}-15T00:00:00`) : new Date()
  const daysInMonth = new Date(ref.getFullYear(), ref.getMonth() + 1, 0).getDate()
  const byDay = new Map(rows.map(r => [Number(r.d.slice(8, 10)), r]))
  const nets = rows.map(r => r.paid_out - r.paid_in)
  const maxAbs = Math.max(...nets.map(Math.abs), 1)
  let cum = 0
  const cums: (number | null)[] = []
  for (let day = 1; day <= daysInMonth; day++) {
    const r = byDay.get(day)
    if (r) { cum += r.paid_out - r.paid_in; cums.push(cum) } else cums.push(byDay.size && day <= Number(rows[rows.length - 1]?.d.slice(8, 10)) ? cum : null)
  }
  const cumMax = Math.max(...cums.filter((c): c is number => c !== null).map(Math.abs), maxAbs)
  const W = 720, H = 150, M = { t: 10, b: 22, l: 8, r: 64 }
  const bw = (W - M.l - M.r) / daysInMonth
  const y = (v: number) => M.t + (1 - (v + cumMax) / (2 * cumMax)) * (H - M.t - M.b)
  const zero = y(0)
  let cumPath = ''
  cums.forEach((c, i) => {
    if (c === null) return
    const x = M.l + (i + 0.5) * bw
    cumPath += (cumPath ? 'L' : 'M') + x.toFixed(1) + ',' + y(c).toFixed(1)
  })
  const lastCum = [...cums].reverse().find(c => c !== null) ?? 0
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block select-none" role="img"
         aria-label="Daily net payout for this position across the delivery month">
      <line x1={M.l} x2={W - M.r} y1={zero} y2={zero} stroke="#3a4f58" strokeWidth={1} />
      {Array.from({ length: daysInMonth }, (_, i) => {
        const day = i + 1
        const r = byDay.get(day)
        const x = M.l + i * bw + 1
        if (!r) {
          return <line key={day} x1={x + bw / 2 - 1} x2={x + bw / 2 - 1} y1={zero - 1} y2={zero + 1} stroke="#2c424c" strokeWidth={1.5} />
        }
        const net = r.paid_out - r.paid_in
        const yTop = net >= 0 ? y(net) : zero
        const h = Math.max(Math.abs(zero - y(net)), 1.5)
        return (
          <g key={day}>
            <rect x={x} y={yTop} width={Math.max(bw - 2, 2)} height={h} rx={1.5}
              fill={net >= 0 ? '#34d399' : '#f87171'} fillOpacity={0.85}>
              <title>{`${r.d}: paid out $${r.paid_out.toLocaleString()} vs $${r.paid_in.toLocaleString()} in — net ${net >= 0 ? '+' : '−'}$${Math.abs(net).toLocaleString()}`}</title>
            </rect>
          </g>
        )
      })}
      <path d={cumPath} fill="none" stroke="#93a6ab" strokeWidth={1.5} strokeDasharray="4 3" />
      <text x={W - M.r + 6} y={y(lastCum) + 4} fontSize={12} fill={lastCum >= 0 ? '#34d399' : '#f87171'}>
        {lastCum >= 0 ? '+' : '−'}${Math.abs(lastCum).toLocaleString()} net
      </text>
      {[1, 10, 20, daysInMonth].map(d => (
        <text key={d} x={M.l + (d - 0.5) * bw} y={H - 6} textAnchor="middle" fontSize={11} fill="#61767e">{d}</text>
      ))}
    </svg>
  )
}
