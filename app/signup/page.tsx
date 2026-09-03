'use client'
import { useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'
import { LogoMark } from '../logo'

export default function SignUp() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg(null)
    const { data, error } = await sb.auth.signUp({ email, password })
    setBusy(false)
    if (error) { setMsg(error.message); return }
    if (data.session) { window.location.href = '/app'; return }
    setMsg('Check your email to confirm your account, then sign in.')
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4 text-[#f2f6f6]">
      <div className="w-full max-w-sm">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></Link>
        <h1 className="mt-6 text-lg font-medium">Start your free trial</h1>
        <p className="mt-1 text-xs text-[#7d9096]">
          30 days free. Every auction sheet while it lasts. No card required.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
            placeholder="work email"
            className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          <input type="password" required minLength={8} value={password}
            onChange={e => setPassword(e.target.value)} placeholder="password (8+ characters)"
            className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          <button disabled={busy}
            className="w-full rounded bg-[#eda63a] px-3 py-2 text-sm font-medium text-[#15242c] hover:bg-[#f5b95c] disabled:opacity-50">
            {busy ? 'creating…' : 'Create account'}
          </button>
        </form>
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
        <p className="mt-6 text-xs text-[#7d9096]">
          Already have an account? <Link href="/signin" className="text-[#dbe4e6] hover:text-white">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
