'use client'
import { useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'
import { AUCTION_MONTH, NEXT_AUCTION, NEXT_MONTH, OPENS_LABEL, daysToClose } from '@/lib/auction'
import { LogoMark } from '../logo'

export default function SignUp() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg(null)
    const { data, error } = await sb.auth.signUp({
      email, password,
      // land the confirmation click signed-in on the Today page: /app loads
      // the supabase client, which picks the session out of the redirect
      options: { emailRedirectTo: `${window.location.origin}/app` },
    })
    setBusy(false)
    if (error) { setMsg(error.message); return }
    if (data.session) { window.location.href = '/app'; return }
    setSent(true)
  }

  if (sent) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink px-4 text-[#f2f6f6]">
        <div className="w-full max-w-sm">
          <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></Link>
          <div className="mt-6 rounded border border-line bg-panel p-5">
            <h1 className="text-lg font-medium">Check your email</h1>
            <p className="mt-2 text-sm leading-relaxed text-[#93a6ab]">
              A confirmation just went to <span className="text-[#dbe4e6]">{email}</span>.
              One click there and you&apos;ll land back here signed in, trial running.
            </p>
            <p className="mt-3 text-xs text-[#7d9096]">
              Nothing after a couple of minutes? Check spam, or{' '}
              <button onClick={() => setSent(false)} className="text-[#93a6ab] underline hover:text-[#dbe4e6]">
                try again
              </button>.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4 text-[#f2f6f6]">
      <div className="w-full max-w-sm">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></Link>
        <h1 className="mt-6 text-lg font-medium">Start your free trial</h1>
        <p className="mt-1 text-xs text-[#7d9096]">
          30 days free, no card. {daysToClose() >= 0
            ? `${AUCTION_MONTH} auction bids open ${OPENS_LABEL}`
            : `${NEXT_MONTH} auction bids open ${new Date(`${NEXT_AUCTION.opens}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}`} — your sheet will be ready.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <div>
            <label htmlFor="email" className="mb-1 block text-xs text-[#93a6ab]">Work email</label>
            <input id="email" type="email" required value={email} onChange={e => setEmail(e.target.value)}
              autoComplete="email" inputMode="email"
              className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          </div>
          <div>
            <label htmlFor="password" className="mb-1 block text-xs text-[#93a6ab]">Password (8+ characters)</label>
            <input id="password" type="password" required minLength={8} value={password}
              onChange={e => setPassword(e.target.value)} autoComplete="new-password"
              className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          </div>
          <button disabled={busy}
            className="w-full rounded bg-[#eda63a] px-3 py-2 text-sm font-medium text-[#15242c] hover:bg-[#f5b95c] disabled:opacity-50">
            {busy ? 'creating…' : 'Create account'}
          </button>
        </form>
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
        <p className="mt-3 text-[11px] leading-relaxed text-[#7d9096]">
          By creating an account you agree to the{' '}
          <Link href="/terms" className="text-[#93a6ab] hover:text-[#dbe4e6]">Terms of Service</Link> and{' '}
          <Link href="/privacy" className="text-[#93a6ab] hover:text-[#dbe4e6]">Privacy Policy</Link>.
        </p>
        <p className="mt-6 text-xs text-[#7d9096]">
          Already have an account? <Link href="/signin" className="text-[#dbe4e6] hover:text-white">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
