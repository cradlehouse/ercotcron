// Shared presentation pieces. Server components — nothing here is interactive.

import { formatRelative } from '@/lib/prices'

export function Panel({
  title,
  subtitle,
  right,
  children,
}: {
  title: string
  subtitle?: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded border border-line bg-panel">
      <div className="flex items-baseline gap-3 border-b border-line px-4 py-2.5">
        <h2 className="font-semibold tracking-tight text-zinc-200">{title}</h2>
        {subtitle && <span className="text-[11px] text-zinc-600">{subtitle}</span>}
        {right && <div className="ml-auto">{right}</div>}
      </div>
      {children}
    </section>
  )
}

/**
 * Every page must survive an empty database: until the first ingest run lands,
 * every query legitimately returns nothing, and a blank screen is
 * indistinguishable from a broken one.
 */
export function Empty({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="text-zinc-500">{message}</p>
      {hint && <p className="mt-1.5 text-[11px] text-zinc-600">{hint}</p>}
    </div>
  )
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <div className="border-b border-red-500/25 bg-red-500/10 px-4 py-2.5 text-red-300">
      <span className="font-semibold">query failed</span>
      <span className="ml-2 text-red-300/80">{error}</span>
    </div>
  )
}

export function Stat({
  label,
  value,
  tone = 'text-zinc-200',
  note,
}: {
  label: string
  value: React.ReactNode
  tone?: string
  note?: string
}) {
  return (
    <div className="rounded border border-line bg-panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-zinc-600">{label}</div>
      <div className={`tnum mt-1 text-xl font-semibold ${tone}`}>{value}</div>
      {note && <div className="mt-0.5 text-[11px] text-zinc-600">{note}</div>}
    </div>
  )
}

/** A staleness chip: the number an operator checks first. */
export function Freshness({ label, at }: { label: string; at: string | null }) {
  const ms = at ? new Date(at).getTime() : null
  const age = ms === null ? Infinity : (Date.now() - ms) / 1000
  const tone =
    age === Infinity ? 'text-zinc-600' : age < 900 ? 'text-emerald-300' : age < 3600 ? 'text-amber-300' : 'text-red-400'

  return (
    <div className="flex items-baseline gap-2 rounded border border-line bg-panel-2 px-3 py-1.5">
      <span className="text-[11px] text-zinc-500">{label}</span>
      <span className={`tnum ${tone}`}>{at ? formatRelative(at) : 'never'}</span>
    </div>
  )
}

const STATUS_TONE: Record<string, string> = {
  ok: 'text-emerald-300',
  // 'empty' is a warning, not a success: the request worked and returned no
  // rows, which is the signature of a wrong ERCOT query parameter name.
  empty: 'text-amber-300',
  error: 'text-red-400',
  running: 'text-sky-300',
}

export function StatusChip({ status }: { status: string }) {
  return (
    <span className={`font-semibold ${STATUS_TONE[status] ?? 'text-zinc-400'}`}>{status}</span>
  )
}
