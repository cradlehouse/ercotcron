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
    ? `<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#93a6ab;margin-bottom:10px">Access request</div>
       <h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Access confirmed.</h2>
       <p style="margin:0;font-size:14px;line-height:1.6;color:#93a6ab">The claim on this CRR account is approved. The requester can now see the book, graded, at <a href="https://shadowprice.io/app" style="color:#eda63a">shadowprice.io</a>.</p>`
    : `<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#93a6ab;margin-bottom:10px">Access request</div>
       <h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Link invalid or expired.</h2>
       <p style="margin:0;font-size:14px;line-height:1.6;color:#93a6ab">Nothing was changed. Claims can be re-requested from the member area at <a href="https://shadowprice.io/app" style="color:#eda63a">shadowprice.io</a>.</p>`
  return new NextResponse(
    `<!doctype html><html><body style="margin:0;background:#15242c;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif">
      <div style="max-width:520px;margin:14vh auto;padding:0 20px">
        <div style="font-size:17px;font-weight:700;letter-spacing:-0.01em;color:#f2f6f6;margin-bottom:26px"><span style="color:#eda63a">shadow</span>price</div>
        <div style="background:#1e3038;border-radius:10px;padding:28px">${body}</div>
        <div style="margin-top:16px;font-size:11px;color:#61767e">— The Shadowprice team · we hold no CRR positions</div>
      </div>
    </body></html>`,
    { status: ok ? 200 : 400, headers: { 'Content-Type': 'text/html' } },
  )
}
