// POST /api/billing/checkout { tier? } — start a Stripe Checkout subscription
// for the signed-in member. Returns { url } to redirect to.
//
// A member still inside the free trial is not charged early: the
// subscription's trial_end is set to the app trial's last day, so the card
// is collected now and the first charge lands when the trial would have
// lapsed. That is the whole point — the trial no longer ends in a dead gate.
import { NextRequest, NextResponse } from 'next/server'
import { TIERS, type Tier, callerProfile, stripe } from '@/lib/billing'

export async function POST(req: NextRequest) {
  const s = stripe()
  if (!s) return NextResponse.json({ error: 'billing is not configured' }, { status: 503 })
  const me = await callerProfile(req.headers.get('authorization') ?? '')
  if (!me) return NextResponse.json({ error: 'sign in first' }, { status: 401 })
  if (me.plan === 'comp' || me.plan === 'active') {
    return NextResponse.json({ error: 'already on a plan' }, { status: 409 })
  }

  const { tier = 'sheet' } = await req.json().catch(() => ({}))
  const price = TIERS[tier as Tier]
  if (!price) return NextResponse.json({ error: `tier '${tier}' is not for sale` }, { status: 400 })

  // Stripe requires trial_end at least 48h out; a trial closer than that
  // simply starts billing now.
  const trialEnd = me.plan === 'trial' && me.trial_ends
    ? Math.floor(new Date(`${me.trial_ends}T23:59:00-05:00`).getTime() / 1000)
    : null
  const keepTrial = trialEnd !== null && trialEnd - Date.now() / 1000 > 48 * 3600

  const origin = req.nextUrl.origin
  const session = await s.checkout.sessions.create({
    mode: 'subscription',
    line_items: [{ price, quantity: 1 }],
    client_reference_id: me.user_id,
    ...(me.stripe_customer_id ? { customer: me.stripe_customer_id } : { customer_email: me.email }),
    subscription_data: {
      metadata: { user_id: me.user_id, tier },
      ...(keepTrial ? { trial_end: trialEnd! } : {}),
    },
    metadata: { user_id: me.user_id, tier },
    allow_promotion_codes: true,
    success_url: `${origin}/app?billing=success`,
    cancel_url: `${origin}/app?billing=cancelled`,
  })
  return NextResponse.json({ url: session.url })
}
