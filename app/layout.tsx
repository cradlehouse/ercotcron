import type { Metadata } from 'next'
import Link from 'next/link'

import './globals.css'

export const metadata: Metadata = {
  title: 'ercotcron',
  description: 'ERCOT price ingestion monitor',
}

const NAV = [
  { href: '/', label: 'monitor' },
  { href: '/spikes', label: 'spikes' },
  { href: '/health', label: 'health' },
]

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-line bg-panel">
          <div className="mx-auto flex max-w-[1400px] items-center gap-6 px-5 py-2.5">
            <span className="font-semibold tracking-tight text-zinc-200">ercotcron</span>
            <nav className="flex gap-4">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-zinc-500 transition-colors hover:text-zinc-200"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <span className="ml-auto text-[11px] text-zinc-600">
              times in ERCOT local (America/Chicago)
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
      </body>
    </html>
  )
}
