// The public methodology — the document the Terms point at. Rendered straight
// from docs/MARK_METHODOLOGY.md so the site can never drift from the versioned
// document counsel and customers see. Nothing proprietary stands between a
// skeptic and verification; that is the point.
import fs from 'node:fs'
import path from 'node:path'
import Link from 'next/link'
import { marked } from 'marked'
import { LogoMark } from '../logo'

export const metadata = {
  title: 'Methodology — Shadowprice',
  description: 'How Shadowprice marks ERCOT CRR positions: inputs, controls, error rates, and what the mark is not.',
}

export default function MethodologyPage() {
  const md = fs.readFileSync(path.join(process.cwd(), 'docs', 'MARK_METHODOLOGY.md'), 'utf8')
  const html = marked.parse(md, { async: false }) as string
  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span>
        </Link>
        <Link href="/terms" className="text-xs text-[#7d9096] hover:text-[#dbe4e6]">Terms</Link>
      </header>
      <main className="mx-auto max-w-3xl px-6 pb-16">
        <article
          className="prose-invert space-y-4 text-[13.5px] leading-relaxed text-[#93a6ab]
                     [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:text-[#f2f6f6]
                     [&_h2]:mt-8 [&_h2]:text-[15px] [&_h2]:font-semibold [&_h2]:text-[#f2f6f6]
                     [&_h3]:mt-5 [&_h3]:text-[13.5px] [&_h3]:font-semibold [&_h3]:text-[#dbe4e6]
                     [&_strong]:text-[#dbe4e6] [&_a]:text-[#eda63a]
                     [&_li]:ml-5 [&_li]:list-disc
                     [&_table]:w-full [&_table]:border-collapse [&_table]:text-[12.5px]
                     [&_th]:border-b [&_th]:border-[#2c424c] [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-[#dbe4e6]
                     [&_td]:border-b [&_td]:border-[#2c424c]/60 [&_td]:px-2 [&_td]:py-1.5
                     [&_code]:rounded [&_code]:bg-[#1e3038] [&_code]:px-1 [&_code]:text-[#dbe4e6]"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </main>
    </div>
  )
}
