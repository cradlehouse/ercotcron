'use client'
// Landing for the password-reset email: the link carries a recovery session;
// this page sets the new password against it.
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { sb } from '@/lib/supabase'
import { LogoMark } from '../logo'

export default function Reset() {
  const [ready, setReady] = useState(false)
  const [password, setPassword] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    sb.auth.getSession().then(({ data }) => {
      if (!data.session) {
        setMsg('This link is invalid or expired — request a new one from the sign-in page.')
      }
      setReady(true)
    })
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setMsg(null)
    const { error } = await sb.auth.updateUser({ password })
    setBusy(false)
    if (error) { setMsg(error.message); return }
    window.location.href = '/app'
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4 text-[#f2f6f6]">
      <div className="w-full max-w-sm">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></Link>
        <h1 className="mt-6 text-lg font-medium">Set a new password</h1>
        {ready && (
          <form onSubmit={submit} className="mt-6 space-y-3">
            <input type="password" required minLength={8} value={password}
              onChange={e => setPassword(e.target.value)} placeholder="new password (8+ characters)"
              className="w-full rounded border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[#eda63a]" />
            <button disabled={busy}
              className="w-full rounded bg-[#eda63a] px-3 py-2 text-sm font-medium text-[#15242c] hover:bg-[#f5b95c] disabled:opacity-50">
              {busy ? 'saving…' : 'Save and sign in'}
            </button>
          </form>
        )}
        {msg && <p className="mt-3 text-xs text-amber-400">{msg}</p>}
      </div>
    </div>
  )
}
