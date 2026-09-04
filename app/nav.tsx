'use client'
// The product menu — five words, meaningful to a trader or a banker.
// Hidden on pages that carry their own header (landing, auth). The ops pages
// keep working by URL but no longer clutter anyone's navigation.
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'
import { LogoMark } from './logo'

const SELF_HEADED = ['/', '/signin', '/signup', '/terms', '/privacy']
const MENU = [
  { href: '/app', label: 'Today' },
  { href: '/bids', label: 'Bid sheets' },
  { href: '/bids/strip', label: 'Long-term 2028' },
  { href: '/app/book', label: 'My book' },
  { href: '/map', label: 'Map' },
]

export function NavBar() {
  const path = usePathname()
  const [email, setEmail] = useState<string | null>(null)
  useEffect(() => {
    sb.auth.getSession().then(({ data }) => setEmail(data.session?.user.email ?? null))
  }, [])
  if (SELF_HEADED.includes(path)) return null
  return (
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex max-w-[1400px] items-center gap-5 px-5 py-2.5">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-[#f2f6f6]">
          <LogoMark size={20} />
          <span><span className="text-[#eda63a]">shadow</span>price</span>
        </Link>
        <nav className="flex gap-4 text-[13px]">
          {MENU.map(m => (
            <Link key={m.href} href={m.href}
              className={path === m.href ? 'text-[#f2f6f6]' : 'text-[#7d9096] hover:text-[#dbe4e6]'}>
              {m.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-[12px] text-[#7d9096]">
          {email ? (
            <>
              <span className="hidden sm:inline">{email}</span>
              <button onClick={() => sb.auth.signOut().then(() => { window.location.href = '/' })}
                className="hover:text-[#dbe4e6]">Sign out</button>
            </>
          ) : (
            <Link href="/signin" className="hover:text-[#dbe4e6]">Sign in</Link>
          )}
        </div>
      </div>
    </header>
  )
}
