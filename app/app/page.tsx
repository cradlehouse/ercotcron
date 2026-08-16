'use client'
// Member home: trial status + the products. Decision-focused, not a terminal.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'

type Profile = { plan: string; trial_ends: string | null }

export default function MemberHome() {
  const [email, setEmail] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      setEmail(data.session.user.email ?? null)
      const { data: p } = await sb.from('profiles')
        .select('plan, trial_ends').eq('user_id', data.session.user.id).single()
      setProfile((p as unknown as Profile) ?? { plan: 'trial', trial_ends: null })
      setReady(true)
    })
  }, [])

  if (!ready) return <div className="p-6 text-sm text-neutral-400">loading…</div>

  const trialDays = profile?.trial_ends
    ? Math.max(0, Math.ceil((new Date(profile.trial_ends).getTime() - Date.now()) / 86400000))
    : null

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="mx-auto flex max-w-4xl items-center justify-between px-6 py-5">
        <span className="text-sm font-semibold tracking-tight">shadowprice</span>
        <div className="flex items-center gap-3 text-xs text-neutral-400">
          <span>{email}</span>
          <button onClick={() => sb.auth.signOut().then(() => { window.location.href = '/' })}
            className="hover:text-neutral-200">Sign out</button>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <div className="rounded border border-neutral-800 bg-neutral-900/50 px-4 py-3 text-xs text-neutral-400">
          {profile?.plan === 'trial'
            ? <>Free trial{trialDays !== null ? ` — ${trialDays} days left` : ''}. Billing setup arrives before your trial ends; nothing is charged until you choose to stay.</>
            : <>Plan: {profile?.plan}</>}
        </div>

        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          <section className="rounded border border-neutral-800 p-4">
            <div className="text-sm font-medium">Next auction</div>
            <p className="mt-1 text-xs leading-relaxed text-neutral-400">
              OCT 2026 monthly — bids Sep 8–10. Your sheet posts here when the
              scan for the delivery month completes, with limits, sizing, and
              the ERCOT-format CSV.
            </p>
            <a href="/bids" className="mt-3 inline-block rounded bg-cyan-400 px-3 py-1.5 text-xs font-medium text-neutral-950 hover:bg-cyan-300">
              Open current bid sheet
            </a>
          </section>

          <section className="rounded border border-neutral-800 p-4">
            <div className="text-sm font-medium">Relationship map</div>
            <p className="mt-1 text-xs leading-relaxed text-neutral-400">
              Every live path and the constraints behind it — hover a node to
              see what drives it and what it drags along.
            </p>
            <a href="/map" className="mt-3 inline-block rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-200 hover:bg-neutral-900">
              Open map
            </a>
          </section>

          <section className="rounded border border-neutral-800 p-4">
            <div className="text-sm font-medium">Constraint alerts</div>
            <p className="mt-1 text-xs leading-relaxed text-neutral-400">
              Re-rates, retirements, and relief projects behind the paths you
              care about. Email alerts are being wired now — trial members get
              them first.
            </p>
          </section>

          <section className="rounded border border-neutral-800 p-4">
            <div className="text-sm font-medium">Track record</div>
            <p className="mt-1 text-xs leading-relaxed text-neutral-400">
              Every sheet self-scored against what the auction and settlement
              actually did. First public scorecard publishes after the
              September settlement.
            </p>
          </section>
        </div>

        <p className="mt-8 text-[11px] leading-relaxed text-neutral-600">
          Shadowprice holds no CRR positions. Analytics derive from public
          ERCOT data; valuations are anchored on realized settlement history
          and are not forecasts or investment advice.
        </p>
      </main>
    </div>
  )
}
