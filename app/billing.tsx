'use client'
// Billing UI: the subscribe / manage-billing buttons and the lapsed-plan card.
// The server routes (app/api/billing/*) do the Stripe work; these only POST
// with the member's bearer token and follow the returned URL.
import { useState } from 'react'
import { sb } from '@/lib/supabase'

export type PlanProfile = { plan: string; trial_ends: string | null; role?: string | null }

/** Mirrors has_active_plan() in the database — the database is the real
 *  gate; this only decides what to render. */
export function planActive(p: PlanProfile | null): boolean {
  if (!p) return false
  if (p.role === 'admin' || p.plan === 'active' || p.plan === 'comp') return true
  if (p.plan !== 'trial' || !p.trial_ends) return false
  return p.trial_ends >= new Date().toLocaleDateString('en-CA', { timeZone: 'America/Chicago' })
}

async function go(path: string, body: object = {}): Promise<string | null> {
  const { data } = await sb.auth.getSession()
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${data.session?.access_token}` },
    body: JSON.stringify(body),
  }).then(x => x.json()).catch(() => ({ error: 'network error' }))
  if (r.url) {
    window.location.href = r.url
    return null
  }
  return r.error ?? 'something went wrong'
}

/** Off until Stripe keys exist in the environment: a button that can only
 *  answer "billing is not configured" is worse than no button. */
export const BILLING_ENABLED = process.env.NEXT_PUBLIC_BILLING_ENABLED === '1'

export function BillingButton({ mode, label }: { mode: 'subscribe' | 'manage'; label?: string }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  if (!BILLING_ENABLED) {
    return mode === 'subscribe'
      ? <a href="mailto:team@shadowprice.io?subject=Shadowprice%20subscription" className="text-[13px] text-[#eda63a]">Email us to subscribe</a>
      : null
  }
  return (
    <span className="inline-flex flex-col">
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true); setErr(null)
          const e = await go(mode === 'subscribe' ? '/api/billing/checkout' : '/api/billing/portal',
            mode === 'subscribe' ? { tier: 'sheet' } : {})
          if (e) { setErr(e); setBusy(false) }
        }}
        className={mode === 'subscribe'
          ? 'rounded bg-[#eda63a] px-3 py-1.5 text-[13px] font-medium text-[#15242c] disabled:opacity-50'
          : 'rounded border border-line px-3 py-1.5 text-[13px] text-[#dbe4e6] disabled:opacity-50'}>
        {busy ? 'Opening…' : label ?? (mode === 'subscribe' ? 'Subscribe' : 'Manage billing')}
      </button>
      {err && <span className="mt-1 text-[12px] text-amber-400">{err}</span>}
    </span>
  )
}

export function LapsedCard() {
  return (
    <div className="mx-auto max-w-md px-6 py-16 text-[#f2f6f6]">
      <h1 className="text-lg font-medium">Your trial has ended</h1>
      <p className="mt-2 text-[13.5px] leading-relaxed text-[#93a6ab]">
        The sheet, your graded book and the method record are for subscribers. The public
        record stays open at <a href="/record" className="text-[#eda63a]">/record</a>.
      </p>
      <div className="mt-5"><BillingButton mode="subscribe" label="Subscribe to keep access" /></div>
    </div>
  )
}
