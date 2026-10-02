// Server-only billing helpers. Stripe holds the money; profiles.plan holds the
// gate (see supabase/migrations/20261002100000_billing.sql). Nothing here is
// imported by a client component.
import Stripe from 'stripe'
import { createClient } from '@supabase/supabase-js'

/** Tiers a member can buy, each mapped to a Stripe Price id in env. A tier
 *  whose env var is unset is simply not for sale yet. */
export const TIERS = {
  sheet: process.env.STRIPE_PRICE_SHEET,
  deploy: process.env.STRIPE_PRICE_DEPLOY,
} as const
export type Tier = keyof typeof TIERS

export function tierForPrice(priceId: string | undefined | null): Tier | null {
  for (const [tier, id] of Object.entries(TIERS)) if (id && id === priceId) return tier as Tier
  return null
}

export function stripe(): Stripe | null {
  const key = process.env.STRIPE_SECRET_KEY
  return key ? new Stripe(key) : null
}

/** A Supabase client acting AS the caller (their bearer token), so RLS scopes
 *  every read to their own rows. */
export function asCaller(auth: string) {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { global: { headers: { Authorization: auth } } },
  )
}

export type BillingProfile = {
  user_id: string
  email: string
  plan: string
  trial_ends: string | null
  stripe_customer_id: string | null
}

/** The signed-in caller and their profile, or null when the token is bad. */
export async function callerProfile(auth: string): Promise<BillingProfile | null> {
  if (!auth.startsWith('Bearer ')) return null
  const sb = asCaller(auth)
  const { data: u } = await sb.auth.getUser(auth.slice(7))
  if (!u?.user) return null
  const { data } = await sb.from('profiles')
    .select('user_id, email, plan, trial_ends, stripe_customer_id')
    .eq('user_id', u.user.id).single()
  return (data as BillingProfile | null) ?? null
}
