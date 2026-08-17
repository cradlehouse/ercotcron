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

  if (!ready) return <div className="p-6 text-sm text-[#93a6ab]">loading…</div>

  const trialDays = profile?.trial_ends
    ? Math.max(0, Math.ceil((new Date(profile.trial_ends).getTime() - Date.now()) / 86400000))
    : null

  return (
    <div className="min-h-screen bg-ink text-[#f2f6f6]">
      <header className="mx-auto flex max-w-4xl items-center justify-between px-6 py-5">
        <span className="text-sm font-semibold tracking-tight">shadowprice</span>
        <div className="flex items-center gap-3 text-xs text-[#93a6ab]">
          <span>{email}</span>
          <button onClick={() => sb.auth.signOut().then(() => { window.location.href = '/' })}
            className="hover:text-[#dbe4e6]">Sign out</button>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-8">
        <div className="rounded border border-line bg-panel/60 px-4 py-3 text-xs text-[#93a6ab]">
          {profile?.plan === 'trial'
            ? <>Free trial{trialDays !== null ? ` — ${trialDays} days left` : ''}. Billing setup arrives before your trial ends; nothing is charged until you choose to stay.</>
            : <>Plan: {profile?.plan}</>}
        </div>

        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          <section className="rounded border border-line p-4">
            <div className="text-sm font-medium">Next auction</div>
            <p className="mt-1 text-xs leading-relaxed text-[#93a6ab]">
              OCT 2026 monthly — bids Sep 8–10. Your sheet posts here when the
              scan for the delivery month completes, with limits, sizing, and
              the ERCOT-format CSV.
            </p>
            <a href="/bids" className="mt-3 inline-block rounded bg-[#eda63a] px-3 py-1.5 text-xs font-medium text-[#15242c] hover:bg-[#f5b95c]">
              Open current bid sheet
            </a>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-sm font-medium">Relationship map</div>
            <p className="mt-1 text-xs leading-relaxed text-[#93a6ab]">
              Every live path and the constraints behind it — hover a node to
              see what drives it and what it drags along.
            </p>
            <a href="/map" className="mt-3 inline-block rounded border border-line px-3 py-1.5 text-xs text-[#dbe4e6] hover:bg-panel">
              Open map
            </a>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-sm font-medium">Constraint alerts</div>
            <p className="mt-1 text-xs leading-relaxed text-[#93a6ab]">
              Re-rates, retirements, and relief projects behind the paths you
              care about. Email alerts are being wired now — trial members get
              them first.
            </p>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-sm font-medium">Track record</div>
            <p className="mt-1 text-xs leading-relaxed text-[#93a6ab]">
              Every sheet self-scored against what the auction and settlement
              actually did. First public scorecard publishes after the
              September settlement.
            </p>
          </section>
        </div>

        <p className="mt-8 text-[11px] leading-relaxed text-[#61767e]">
          Shadowprice holds no CRR positions. Analytics derive from public
          ERCOT data; valuations are anchored on realized settlement history
          and are not forecasts or investment advice.
        </p>
      </main>
    </div>
  )
}
