// GET /api/verify-holder?token=... — the link sent to a holder's registered
// contact address. The token is the proof; no login required to confirm.
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('token') ?? ''
  const sb = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )
  const { data, error } = await sb.rpc('confirm_holder', { p_token: token })
  const ok = !error && data === 'approved'
  const body = ok
    ? '<h2>Access confirmed.</h2><p>The claim on this CRR account is approved. The requester can now see the book at shadowprice.</p>'
    : '<h2>Link invalid or expired.</h2><p>Nothing was changed. Claims can be re-requested from the member area.</p>'
  return new NextResponse(
    `<!doctype html><body style="font-family:system-ui;max-width:48ch;margin:12vh auto;color:#1c2622">${body}</body>`,
    { status: ok ? 200 : 400, headers: { 'Content-Type': 'text/html' } },
  )
}
