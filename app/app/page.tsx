'use client'
// Member home: trial status + the products. Decision-focused, not a terminal.
import { useEffect, useState } from 'react'
import { rpc } from '@/lib/rpc'
import { AUCTION_MONTH, NEXT_AUCTION, NEXT_MONTH, WINDOW_LABEL, daysToClose } from '@/lib/auction'
import { sb } from '@/lib/supabase'
import { BillingButton, planActive } from '../billing'

type Profile = { plan: string; trial_ends: string | null; role?: string | null; subscription_status?: string | null; current_period_end?: string | null }
type Claim = { holder_code: string; status: string }

// Bump when the Terms of Service materially change: every member is asked to
// agree to the new version once, and each agreement is stored append-only
// (accept_terms RPC) as clickwrap acceptance evidence.
const TERMS_VERSION = '2026-09-05'

export default function MemberHome() {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [ready, setReady] = useState(false)
  const [claims, setClaims] = useState<Claim[]>([])
  const [code, setCode] = useState('')
  const [claimMsg, setClaimMsg] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<boolean | null>(null)
  const [agreeTick, setAgreeTick] = useState(false)

  useEffect(() => {
    // The layout's MemberGate guarantees a session; getSession here is only
    // for the user id the profile query needs.
    sb.auth.getSession().then(async ({ data }) => {
      if (!data.session) return
      const { data: p } = await sb.from('profiles')
        .select('plan, trial_ends, role, subscription_status, current_period_end')
        .eq('user_id', data.session.user.id).single()
      setProfile((p as unknown as Profile) ?? { plan: 'trial', trial_ends: null })
      const [{ data: cl }, { data: acc }] = await Promise.all([
        rpc<Claim[]>('my_claims'),
        rpc<boolean>('my_terms_acceptance', { p_version: TERMS_VERSION }),
      ])
      setClaims(cl ?? [])
      setAccepted(Boolean(acc))
      setReady(true)
    })
  }, [])

  if (!ready) return <div className="p-6 text-sm text-[#93a6ab]">loading…</div>

  if (accepted === false) {
    return (
      <div className="mx-auto max-w-md px-6 py-16 text-[#f2f6f6]">
        <h1 className="text-lg font-medium">One thing before the numbers</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-[#93a6ab]">
          Please review and agree to the{' '}
          <a href="/terms" target="_blank" className="text-[#eda63a]">Terms of Service</a> and{' '}
          <a href="/privacy" target="_blank" className="text-[#eda63a]">Privacy Policy</a>{' '}
          (version {TERMS_VERSION}). The short of it: analytics on public data, not investment
          advice; your bidding decisions are yours alone.
        </p>
        <label className="mt-5 flex items-start gap-2 text-[13px] text-[#dbe4e6]">
          <input type="checkbox" checked={agreeTick} onChange={e => setAgreeTick(e.target.checked)}
            className="mt-0.5 accent-[#eda63a]" />
          <span>I have read and agree to the Terms of Service and Privacy Policy.</span>
        </label>
        <button disabled={!agreeTick}
          onClick={async () => {
            await rpc('accept_terms', { p_version: TERMS_VERSION, p_user_agent: navigator.userAgent })
            setAccepted(true)
          }}
          className="mt-4 rounded bg-[#eda63a] px-4 py-2 text-sm font-medium text-[#15242c] disabled:opacity-40">
          Agree and continue
        </button>
      </div>
    )
  }

  const billingNote = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('billing') : null
  const trialDays = profile?.trial_ends
    ? Math.max(0, Math.ceil((new Date(profile.trial_ends).getTime() - Date.now()) / 86400000))
    : null

  return (
    <div className="text-[#f2f6f6]">
      <main className="mx-auto max-w-4xl px-6 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-line bg-panel/60 px-4 py-3 text-[13.5px] text-[#93a6ab]">
          <span>
            {billingNote === 'success'
              ? <>Thanks — your subscription is being confirmed. Refresh in a moment if the plan still reads trial.</>
              : profile?.plan === 'trial' && planActive(profile)
                ? <>Free trial{trialDays !== null ? ` — ${trialDays} day${trialDays === 1 ? '' : 's'} left` : ''}. Subscribe now and the first charge waits until your trial ends.</>
                : profile?.plan === 'comp' || profile?.role === 'admin'
                  ? <>Plan: {profile?.plan} — no billing needed.</>
                  : profile?.plan === 'active'
                    ? <>Subscribed{profile.subscription_status === 'trialing' && profile.current_period_end
                        ? ` — first charge ${new Date(profile.current_period_end).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                        : profile.subscription_status === 'past_due' ? ' — the last payment failed; update your card to keep access' : ''}.</>
                    : <>Your {profile?.plan === 'cancelled' ? 'subscription has ended' : 'trial has ended'}. Subscribe to reopen the sheet, your book and the method record.</>}
          </span>
          {profile?.plan === 'active'
            ? <BillingButton mode="manage" />
            : profile?.plan !== 'comp' && profile?.role !== 'admin' && <BillingButton mode="subscribe" />}
        </div>

        <section className="mt-6 rounded border border-line p-4">
          <div className="text-[15px] font-medium">Your CRR account</div>
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
            <p className="mt-1 text-[13.5px] text-[#93a6ab]">
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
            else if (r.status === 'invalid')
              setClaimMsg("That doesn't look like a CRR account code — a short all-caps code, like XSAAIC.")
            else if (r.status === 'rate_limited')
              setClaimMsg('Too many claim attempts today — try again tomorrow, or email team@shadowprice.io.')
            else if (r.status === 'unknown')
              setClaimMsg("That code isn't in ERCOT's CRR holder registry — check the spelling, or email team@shadowprice.io if the account is newly registered.")
            else setClaimMsg('Something went wrong — try again.')
            const { data: cl } = await rpc<Claim[]>('my_claims')
            setClaims(cl ?? [])
          }}>
            <input value={code} onChange={e => setCode(e.target.value.toUpperCase())}
              placeholder="ACCOUNT CODE"
              className="w-40 rounded border border-line bg-panel px-2 py-1.5 font-mono text-xs outline-none focus:border-[#eda63a]" />
            <button className="rounded bg-[#eda63a] px-3 py-1.5 text-xs font-medium text-[#15242c] hover:bg-[#f5b95c]">
              Claim
            </button>
          </form>
          {claimMsg && <p className="mt-2 text-xs text-[#93a6ab]">{claimMsg}</p>}
          <p className="mt-3 border-t border-line pt-2 text-[11px] leading-relaxed text-[#61767e]">
            We hold no CRR positions, sell no exit intelligence, and never show your book to
            anyone but you. Your positions are already public ERCOT records — what we add is
            the grading, and that goes to the verified holder only.
          </p>
        </section>

        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          <section className="rounded border border-line p-4">
            <div className="text-[15px] font-medium">Next auction</div>
            <p className="mt-1 text-[13.5px] leading-relaxed text-[#93a6ab]">
              {daysToClose() >= 0
                ? `${AUCTION_MONTH} 2026 monthly — bids ${WINDOW_LABEL}.`
                : `${NEXT_MONTH} 2026 monthly — bids open ${new Date(`${NEXT_AUCTION.opens}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}.`} Your bid sheet posts here when
              the October valuation run completes, with limits, sizing, and
              the ERCOT-format CSV.
            </p>
            <a href="/bids" className="mt-3 inline-block rounded bg-[#eda63a] px-3 py-1.5 text-xs font-medium text-[#15242c] hover:bg-[#f5b95c]">
              Open current bid sheet
            </a>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-[15px] font-medium">Relationship map</div>
            <p className="mt-1 text-[13.5px] leading-relaxed text-[#93a6ab]">
              Every live path and the constraints behind it — hover a node to
              see what drives it and what it drags along.
            </p>
            <a href="/map" className="mt-3 inline-block rounded border border-line px-3 py-1.5 text-xs text-[#dbe4e6] hover:bg-panel">
              Open map
            </a>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-[15px] font-medium">Constraint alerts</div>
            <p className="mt-1 text-[13.5px] leading-relaxed text-[#93a6ab]">
              Re-rates, retirements, and relief projects behind the paths you
              care about. Email alerts are being wired now — trial members get
              them first.
            </p>
          </section>

          <section className="rounded border border-line p-4">
            <div className="text-[15px] font-medium">Track record</div>
            <p className="mt-1 text-[13.5px] leading-relaxed text-[#93a6ab]">
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
