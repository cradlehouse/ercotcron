'use client'
import { useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'
import { LogoMark } from '../logo'

export default function SignIn() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg(null)
    const { error } = await sb.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (error) { setMsg(error.message); return }
    window.location.href = '/app'
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4 text-[#f2f6f6]">
      <div className="w-full max-w-sm">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></Link>
        <h1 className="mt-6 text-lg font-medium">Sign in</h1>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
            placeholder="email"
            className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          <input type="password" required value={password}
            onChange={e => setPassword(e.target.value)} placeholder="password"
            className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
          <button disabled={busy}
            className="w-full rounded bg-[#e8eef0] px-3 py-2 text-sm font-medium text-[#15242c] hover:bg-[#f6fafb] disabled:opacity-50">
            {busy ? 'signing in…' : 'Sign in'}
          </button>
        </form>
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
        <p className="mt-6 text-xs text-[#7d9096]">
          New here? <Link href="/signup" className="text-[#dbe4e6] hover:text-white">Start a free trial</Link>
        </p>
      </div>
    </div>
  )
}
