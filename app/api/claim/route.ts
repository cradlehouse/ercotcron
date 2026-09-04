// POST /api/claim { code } — claim a CRRAH holder code for the signed-in user.
// Registry match auto-approves; otherwise a verification link is emailed to
// the holder's REGISTERED contact address (when RESEND_API_KEY is set).
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'
import { claimVerificationEmail } from '@/lib/email'

function mask(email: string): string {
  const [user, domain] = email.split('@')
  return `${user.slice(0, 2)}***@${domain}`
}

export async function POST(req: NextRequest) {
  const auth = req.headers.get('authorization') ?? ''
  if (!auth.startsWith('Bearer ')) {
    return NextResponse.json({ status: 'unauthenticated' }, { status: 401 })
  }
  const sb = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { global: { headers: { Authorization: auth } } },
  )
  const { code } = await req.json().catch(() => ({ code: '' }))
  // The server secret unlocks the verification token + registered email from
  // the RPC; a user calling the RPC directly (without it) learns nothing.
  const { data, error } = await sb.rpc('claim_holder', {
    p_code: String(code ?? ''),
    p_server_secret: process.env.CLAIM_RPC_SECRET ?? process.env.DASH_PASSWORD ?? null,
  })
  if (error) return NextResponse.json({ status: 'error', message: error.message }, { status: 400 })

  const res = data as { status: string; token?: string; registered_email?: string }
  if (res.status !== 'pending' || !res.token || !res.registered_email) {
    return NextResponse.json({ status: res.status })
  }

  const key = process.env.RESEND_API_KEY
  if (!key) {
    // No mail provider yet: manual review remains the path.
    return NextResponse.json({ status: 'pending', delivery: 'manual-review' })
  }
  const origin = req.nextUrl.origin
  const { html, text } = claimVerificationEmail({
    code: String(code).toUpperCase(),
    verifyUrl: `${origin}/api/verify-holder?token=${res.token}`,
  })
  const send = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: process.env.CLAIM_FROM_EMAIL ?? 'verify@shadowprice.io',
      to: res.registered_email,
      subject: `Confirm access to CRR account ${String(code).toUpperCase()} on Shadowprice`,
      html, text,
    }),
  })
  return NextResponse.json({
    status: 'pending',
    delivery: send.ok ? 'emailed' : 'manual-review',
    registered: mask(res.registered_email),
  })
}
