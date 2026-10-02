// POST /api/billing/webhook — Stripe -> profiles.plan.
//
// The signature is verified against STRIPE_WEBHOOK_SECRET over the RAW body
// (req.text(), never parsed first). Accepted events reach the database only
// through billing_apply(), which acts solely for callers holding the server
// secret and is idempotent on Stripe's event id, so redeliveries are no-ops.
import { NextRequest, NextResponse } from 'next/server'
import type Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'
import { stripe, tierForPrice } from '@/lib/billing'

const HANDLED = new Set([
  'checkout.session.completed',
  'customer.subscription.created',
  'customer.subscription.updated',
  'customer.subscription.deleted',
])

export async function POST(req: NextRequest) {
  const s = stripe()
  const whsec = process.env.STRIPE_WEBHOOK_SECRET
  if (!s || !whsec) return NextResponse.json({ error: 'billing is not configured' }, { status: 503 })

  const body = await req.text()
  let event: Stripe.Event
  try {
    event = s.webhooks.constructEvent(body, req.headers.get('stripe-signature') ?? '', whsec)
  } catch {
    return NextResponse.json({ error: 'bad signature' }, { status: 400 })
  }
  if (!HANDLED.has(event.type)) return NextResponse.json({ received: true, ignored: event.type })

  let sub: Stripe.Subscription
  let userId: string | null
  if (event.type === 'checkout.session.completed') {
    const cs = event.data.object as Stripe.Checkout.Session
    if (cs.mode !== 'subscription' || !cs.subscription) return NextResponse.json({ received: true })
    sub = await s.subscriptions.retrieve(String(typeof cs.subscription === 'string' ? cs.subscription : cs.subscription.id))
    userId = cs.client_reference_id ?? cs.metadata?.user_id ?? null
  } else {
    sub = event.data.object as Stripe.Subscription
    userId = sub.metadata?.user_id ?? null
  }

  const item = sub.items?.data?.[0]
  const periodEnd = item?.current_period_end ? new Date(item.current_period_end * 1000).toISOString() : null
  const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!)
  const { data, error } = await sb.rpc('billing_apply', {
    p_secret: process.env.BILLING_RPC_SECRET ?? null,
    p_event_id: event.id,
    p_type: event.type,
    p_user_id: userId,
    p_customer: typeof sub.customer === 'string' ? sub.customer : sub.customer?.id ?? null,
    p_subscription: sub.id,
    p_status: sub.status,
    p_period_end: periodEnd,
    p_tier: tierForPrice(item?.price?.id) ?? sub.metadata?.tier ?? null,
  })
  // A 500 makes Stripe retry with backoff — right for a transient DB error.
  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ received: true, result: data })
}
