import type { Metadata } from 'next'

import './globals.css'
import { NavBar } from './nav'

export const metadata: Metadata = {
  title: 'Shadowprice',
  description: 'Pricing discipline for ERCOT CRRs',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <NavBar />
        <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>
      </body>
    </html>
  )
}
