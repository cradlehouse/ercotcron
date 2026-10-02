// POST /api/billing/portal — Stripe's hosted portal for the signed-in member:
// update the card, see invoices, cancel. Returns { url }.
import { NextRequest, NextResponse } from 'next/server'
import { callerProfile, stripe } from '@/lib/billing'

export async function POST(req: NextRequest) {
  const s = stripe()
  if (!s) return NextResponse.json({ error: 'billing is not configured' }, { status: 503 })
  const me = await callerProfile(req.headers.get('authorization') ?? '')
  if (!me) return NextResponse.json({ error: 'sign in first' }, { status: 401 })
  if (!me.stripe_customer_id) return NextResponse.json({ error: 'no billing account yet' }, { status: 404 })
  const session = await s.billingPortal.sessions.create({
    customer: me.stripe_customer_id,
    return_url: `${req.nextUrl.origin}/app`,
  })
  return NextResponse.json({ url: session.url })
}
