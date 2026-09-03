'use client'
// Member home: trial status + the products. Decision-focused, not a terminal.
import { useEffect, useState } from 'react'
import { sb } from '@/lib/supabase'
import { LogoMark } from '../logo'

type Profile = { plan: string; trial_ends: string | null }
type Claim = { holder_code: string; status: string }

export default function MemberHome() {
  const [email, setEmail] = useState<string | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [ready, setReady] = useState(false)
  const [claims, setClaims] = useState<Claim[]>([])
  const [code, setCode] = useState('')
  const [claimMsg, setClaimMsg] = useState<string | null>(null)

  useEffect(() => {
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) { window.location.href = '/signin'; return }
      setEmail(data.session.user.email ?? null)
      const { data: p } = await sb.from('profiles')
        .select('plan, trial_ends').eq('user_id', data.session.user.id).single()
      setProfile((p as unknown as Profile) ?? { plan: 'trial', trial_ends: null })
      const { data: cl } = await sb.rpc('my_claims')
      setClaims((cl as Claim[]) ?? [])
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
        <span className="flex items-center gap-2 text-sm font-semibold tracking-tight"><LogoMark size={20} /> <span><span className="text-[#eda63a]">shadow</span>price</span></span>
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

        <section className="mt-6 rounded border border-line p-4">
          <div className="text-sm font-medium">Your CRR account</div>
          {claims.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              {claims.map(c => (
                <span key={c.holder_code}
                  className="rounded border border-line px-2 py-1 font-mono">
                  {c.holder_code}
                  <span className={c.status === 'approved' ? 'ml-2 text-emerald-400' : 'ml-2 text-amber-400'}>
                    {c.status}
                  </span>
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-1 text-xs text-[#93a6ab]">
              Enter your ERCOT CRR account code (e.g. XSAAIC) to see your own book, graded.
              If your email matches the account&apos;s registered contact, access is instant;
              otherwise a confirmation goes to the registered address.
            </p>
          )}
          <form className="mt-3 flex gap-2" onSubmit={async e => {
            e.preventDefault(); setClaimMsg(null)
            const { data: sess } = await sb.auth.getSession()
            const tok = sess.session?.access_token
            const r = await fetch('/api/claim', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tok}` },
              body: JSON.stringify({ code }),
            }).then(x => x.json()).catch(() => ({ status: 'error' }))
            if (r.status === 'approved') setClaimMsg('Approved — your book is unlocked.')
            else if (r.status === 'pending' && r.delivery === 'emailed')
              setClaimMsg(`Confirmation sent to the account's registered contact (${r.registered}).`)
            else if (r.status === 'pending') setClaimMsg('Claim received — pending manual review (usually same day).')
            else if (r.status === 'invalid') setClaimMsg('That does not look like a CRRAH code.')
            else setClaimMsg('Something went wrong — try again.')
            const { data: cl } = await sb.rpc('my_claims')
            setClaims((cl as Claim[]) ?? [])
          }}>
            <input value={code} onChange={e => setCode(e.target.value.toUpperCase())}
              placeholder="ACCOUNT CODE"
              className="w-40 rounded border border-line bg-panel px-2 py-1.5 font-mono text-xs outline-none focus:border-[#eda63a]" />
            <button className="rounded bg-[#eda63a] px-3 py-1.5 text-xs font-medium text-[#15242c] hover:bg-[#f5b95c]">
              Claim
            </button>
          </form>
          {claimMsg && <p className="mt-2 text-xs text-[#93a6ab]">{claimMsg}</p>}
        </section>

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
