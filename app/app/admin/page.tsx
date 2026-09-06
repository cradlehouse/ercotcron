'use client'
// Admin is admin: who's here, when they last showed up, what they've claimed.
// Method stays method — this is the operator's desk.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

type AdminUser = {
  email: string; created: string; confirmed: boolean; last_sign_in: string | null
  plan: string | null; role: string | null; trial_ends: string | null
  holders: string[] | null; terms: string | null
}

const ago = (iso: string | null) => {
  if (!iso) return 'never'
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`
  return `${Math.floor(mins / 1440)}d ago`
}
const day = (iso: string | null) => iso ? iso.slice(0, 10) : '—'

export default function AdminScreen() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [state, setState] = useState<'loading' | 'denied' | 'ok'>('loading')

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      const { data: res } = await sb.rpc('get_admin_users')
      const list = (res as { users?: AdminUser[] } | null)?.users
      if (list) { setUsers(list); setState('ok') } else setState('denied')
    })
  }, [])

  if (state === 'loading') return <div className="p-6 text-sm text-[#7d9096]">loading…</div>
  if (state === 'denied' || !users) return <div className="p-6 text-sm text-[#93a6ab]">Nothing here.</div>

  const week = Date.now() - 7 * 86400000
  const active7 = users.filter(u => u.last_sign_in && new Date(u.last_sign_in).getTime() > week).length
  const claimed = users.filter(u => (u.holders?.length ?? 0) > 0).length
  const agreed = users.filter(u => u.terms).length

  return (
    <div className="mx-auto max-w-6xl p-4 text-[#f2f6f6]">
      <h1 className="text-[15px] font-semibold">Admin</h1>
      <p className="mt-1 text-[12.5px] text-[#7d9096]">Users and operations. Not linked anywhere public.</p>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['Users', users.length],
          ['Signed in, 7d', active7],
          ['Claimed a book', claimed],
          ['Accepted terms', agreed],
        ].map(([label, n]) => (
          <div key={label} className="rounded-lg border border-line bg-panel/50 p-3">
            <div className="text-[20px] font-semibold tnum">{n}</div>
            <div className="text-[11px] uppercase tracking-wider text-[#7d9096]">{label}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 overflow-x-auto rounded border border-line bg-panel">
        <table className="w-full min-w-[860px] border-collapse text-[12px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-[#7d9096]">
              <th className="px-2 py-1.5">Email</th><th className="px-2 py-1.5">Plan</th>
              <th className="px-2 py-1.5">Book claims</th><th className="px-2 py-1.5">Terms</th>
              <th className="px-2 py-1.5 text-right">Joined</th>
              <th className="px-2 py-1.5 text-right">Last sign-in</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.email} className="border-b border-line/40 text-[#93a6ab] last:border-0">
                <td className="px-2 py-1.5 font-mono text-[11.5px] text-[#dbe4e6]">
                  {u.email}
                  {u.role === 'admin' && <span className="ml-2 rounded bg-panel-2 px-1.5 py-0.5 text-[10px] text-[#eda63a]">admin</span>}
                  {!u.confirmed && <span className="ml-2 text-[10px] text-red-400/80">unconfirmed</span>}
                </td>
                <td className="px-2 py-1.5">{u.plan ?? '—'}{u.plan === 'trial' && u.trial_ends ? ` → ${u.trial_ends}` : ''}</td>
                <td className="px-2 py-1.5 font-mono text-[11px]">{u.holders?.join(', ') ?? '—'}</td>
                <td className="px-2 py-1.5">{u.terms ? day(u.terms) : <span className="text-[#61767e]">not yet</span>}</td>
                <td className="px-2 py-1.5 text-right tnum">{day(u.created)}</td>
                <td className="px-2 py-1.5 text-right tnum">{ago(u.last_sign_in)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 text-[12.5px] text-[#7d9096]">
        Operations:{' '}
        <a href="/app/method" className="text-[#eda63a] hover:text-[#f5b95c]">method score</a> ·{' '}
        <a href="/monitor" className="text-[#eda63a] hover:text-[#f5b95c]">ingest monitor</a> ·{' '}
        <a href="/scanner" className="text-[#eda63a] hover:text-[#f5b95c]">scanner</a>
      </div>
    </div>
  )
}
