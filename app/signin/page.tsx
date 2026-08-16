'use client'
import { useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'

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
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 px-4 text-neutral-100">
      <div className="w-full max-w-sm">
        <Link href="/" className="text-sm font-semibold tracking-tight">shadowprice</Link>
        <h1 className="mt-6 text-lg font-medium">Sign in</h1>
        <form onSubmit={submit} className="mt-6 space-y-3">
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)}
            placeholder="email"
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600" />
          <input type="password" required value={password}
            onChange={e => setPassword(e.target.value)} placeholder="password"
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600" />
          <button disabled={busy}
            className="w-full rounded bg-neutral-100 px-3 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50">
            {busy ? 'signing in…' : 'Sign in'}
          </button>
        </form>
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
        <p className="mt-6 text-xs text-neutral-500">
          New here? <Link href="/signup" className="text-neutral-300 hover:text-white">Start a free trial</Link>
        </p>
      </div>
    </div>
  )
}
