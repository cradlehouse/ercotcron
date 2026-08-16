'use client'
import { useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'

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
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4 text-neutral-100">
      <div className="w-full max-w-sm">
        <Link href="/" className="text-sm font-semibold tracking-tight">shadowprice</Link>
        <h1 className="mt-6 text-lg font-medium">Start your free trial</h1>
        <p className="mt-1 text-xs text-neutral-500">
          30 days free. Every auction sheet while it lasts. No card required.
        </p>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
            placeholder="work email"
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600" />
          <input type="password" required minLength={8} value={password}
            onChange={e => setPassword(e.target.value)} placeholder="password (8+ characters)"
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600" />
          <button disabled={busy}
            className="w-full rounded bg-cyan-400 px-3 py-2 text-sm font-medium text-neutral-950 hover:bg-cyan-300 disabled:opacity-50">
            {busy ? 'creating…' : 'Create account'}
          </button>
        </form>
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
        <p className="mt-6 text-xs text-neutral-500">
          Already have an account? <Link href="/signin" className="text-neutral-300 hover:text-white">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
