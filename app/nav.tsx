'use client'
// The product menu — five words, meaningful to a trader or a banker.
// Hidden on pages that carry their own header (landing, auth). The ops pages
// keep working by URL but no longer clutter anyone's navigation.
//
// Under 768px the row collapses to brand + hamburger; the menu opens as a
// vertical list with ≥44px tap targets. Plain React state, no library.
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'
import { AUCTION_MONTH, CLOSES_LABEL, daysToClose } from '@/lib/auction'
import { LogoMark } from './logo'

const SELF_HEADED = ['/', '/signin', '/signup', '/reset', '/terms', '/privacy', '/methodology']
const MENU = [
  { href: '/app', label: 'Today' },
  { href: '/bids', label: 'Bid sheets' },
  { href: '/app/book', label: 'My book' },
  { href: '/app/record', label: 'Track record' },
  { href: '/map', label: 'Map' },
]

export function NavBar() {
  const path = usePathname()
  const [email, setEmail] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    sb.auth.getSession().then(({ data }) => setEmail(data.session?.user.email ?? null))
  }, [])
  if (SELF_HEADED.includes(path)) return null

  const daysLeft = daysToClose()
  // One auction badge, driven by lib/auction.ts — never hand-typed here.
  const badge =
    daysLeft >= 0
      ? `${AUCTION_MONTH} bids close ${CLOSES_LABEL} · ${daysLeft}d`
      : `${AUCTION_MONTH} auction closed`

  const signOut = () => sb.auth.signOut().then(() => { window.location.href = '/' })

  return (
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex max-w-[1400px] items-center gap-5 px-5 py-2.5">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-[#f2f6f6]">
          <LogoMark size={20} />
          <span><span className="text-[#eda63a]">shadow</span>price</span>
        </Link>

        {/* Desktop menu */}
        <nav className="hidden gap-4 text-[14px] md:flex">
          {MENU.map(m => (
            <Link key={m.href} href={m.href}
              className={path === m.href ? 'text-[#f2f6f6]' : 'text-[#7d9096] hover:text-[#dbe4e6]'}>
              {m.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto hidden items-center gap-3 text-[13px] text-[#7d9096] md:flex">
          <Link href="/bids"
            className="rounded border border-line bg-ink px-2 py-0.5 text-[11px] text-[#93a6ab] hover:text-[#dbe4e6]">
            {badge}
          </Link>
          {email ? (
            <>
              <span className="hidden lg:inline">{email}</span>
              <button onClick={signOut} className="hover:text-[#dbe4e6]">Sign out</button>
            </>
          ) : (
            <Link href="/signin" className="hover:text-[#dbe4e6]">Sign in</Link>
          )}
        </div>

        {/* Mobile: hamburger */}
        <button
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
          aria-label={open ? 'Close menu' : 'Open menu'}
          className="ml-auto flex h-10 w-10 items-center justify-center rounded text-[#dbe4e6] hover:bg-ink md:hidden"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            {open ? (
              <path d="M4 4l12 12M16 4L4 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            ) : (
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <nav className="border-t border-line bg-panel md:hidden">
          <Link href="/bids" onClick={() => setOpen(false)}
            className="flex min-h-[44px] items-center px-5 text-[12px] text-[#93a6ab]">
            {badge}
          </Link>
          {MENU.map(m => (
            <Link key={m.href} href={m.href} onClick={() => setOpen(false)}
              className={`flex min-h-[44px] items-center px-5 text-[15px] ${
                path === m.href ? 'text-[#f2f6f6]' : 'text-[#93a6ab]'
              }`}>
              {m.label}
            </Link>
          ))}
          {email ? (
            <button onClick={signOut}
              className="flex min-h-[44px] w-full items-center px-5 text-left text-[15px] text-[#93a6ab]">
              Sign out{email ? ` (${email})` : ''}
            </button>
          ) : (
            <Link href="/signin" onClick={() => setOpen(false)}
              className="flex min-h-[44px] items-center px-5 text-[15px] text-[#93a6ab]">
              Sign in
            </Link>
          )}
        </nav>
      )}
    </header>
  )
}
