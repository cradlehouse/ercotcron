'use client'
// The product menu — five words, meaningful to a trader or a banker.
// Hidden on pages that carry their own header (landing, auth). The ops pages
// keep working by URL but no longer clutter anyone's navigation.
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LogoMark } from './logo'

const SELF_HEADED = ['/', '/signin', '/signup', '/terms', '/privacy']
const MENU = [
  { href: '/app', label: 'Today' },
  { href: '/bids', label: 'Bid sheets' },
  { href: '/bids/strip', label: '2028 sheet' },
  { href: '/app/book', label: 'My book' },
  { href: '/map', label: 'Map' },
]

export function NavBar() {
  const path = usePathname()
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
        <Link href="/app" className="ml-auto text-[12px] text-[#7d9096] hover:text-[#dbe4e6]">
          Account
        </Link>
      </div>
    </header>
  )
}
