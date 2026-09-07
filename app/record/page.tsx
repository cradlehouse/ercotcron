// The record, as published — public exhibits (UI review #9).
// Static page, no auth, no live data: the two as-published sheet freezes are
// served verbatim from /public/record/ and linked here with their standing.
import { LogoMark } from '../logo'

export const metadata = { title: 'The record, as published — Shadowprice' }

const EXHIBITS = [
  {
    href: '/record/OCT2026Monthly-2026-09-06.html',
    title: 'OCT 2026 monthly — bid sheet',
    published: 'published 2026-09-06',
    standing: 'Pre-registered: frozen before its auction ran.',
  },
  {
    href: '/record/SEP2026Monthly-reconstructed-2026-09-06.html',
    title: 'SEP 2026 monthly — bid sheet (reconstruction)',
    published: 'published 2026-09-06',
    standing: 'Reconstructed after the fact from pinned pre-auction inputs, labeled as such.',
  },
]

export default function PublicRecord() {
  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
        <a href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span>
        </a>
        <a href="/methodology" className="text-xs text-[#7d9096] hover:text-[#dbe4e6]">Methodology</a>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-16">
        <h1 className="mb-1 text-xl font-semibold">The record, as published</h1>
        <p className="mb-6 max-w-[70ch] text-[13.5px] leading-relaxed text-[#93a6ab]">
          Each sheet below is the exact page as it stood at publication, frozen in an
          append-only store and graded as auction results and settlement arrive. All of it is
          hypothetical — no bids were submitted and no positions were held.
        </p>
        <p className="mb-8 max-w-[70ch] text-[13px] leading-relaxed text-[#7d9096]">
          The two exhibits differ in standing: OCT&nbsp;2026 was frozen <i>before</i> its
          auction ran (pre-registered); SEP&nbsp;2026 is a reconstruction from pinned
          pre-auction inputs made after the fact, labeled as such, and holds itself to the
          same grading.
        </p>

        <div className="space-y-4">
          {EXHIBITS.map(e => (
            <a
              key={e.href}
              href={e.href}
              target="_blank"
              rel="noopener"
              className="block rounded-lg border border-line bg-panel/50 p-4 transition-colors hover:bg-panel-2/40"
            >
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[14px] font-medium text-[#dbe4e6]">{e.title}</span>
                <span className="font-mono text-[11px] text-[#61767e]">{e.published}</span>
              </div>
              <p className="mt-1 text-[12.5px] text-[#93a6ab]">{e.standing}</p>
              <span className="mt-2 inline-block text-[12px] text-[#eda63a]">open the exhibit ↗</span>
            </a>
          ))}
        </div>
      </main>
    </div>
  )
}
