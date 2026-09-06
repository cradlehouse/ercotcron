// Unsubscribe endpoint for outreach email (CAN-SPAM working opt-out).
// Links carry an HMAC signature so only addresses we actually mailed can be
// suppressed — nobody can unsubscribe someone else by guessing.
// GET renders a confirm page (mail scanners prefetch links; the click is the
// opt-out, same pattern as verify-holder); POST records the suppression.
import { createHmac, timingSafeEqual } from 'node:crypto'
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

const SECRET = () => process.env.CLAIM_RPC_SECRET ?? process.env.DASH_PASSWORD ?? ''

function signEmail(email: string): string {
  return createHmac('sha256', SECRET()).update(email.toLowerCase().trim()).digest('hex').slice(0, 24)
}

function verify(email: string, sig: string): boolean {
  const want = signEmail(email)
  return sig.length === want.length &&
    timingSafeEqual(Buffer.from(sig), Buffer.from(want))
}

const HEADERS = { 'Content-Type': 'text/html', 'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex' }

function page(body: string, status = 200): NextResponse {
  return new NextResponse(
    `<!doctype html><html><body style="margin:0;background:#15242c;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif">
      <div style="max-width:520px;margin:14vh auto;padding:0 20px">
        <div style="font-size:17px;font-weight:700;letter-spacing:-0.01em;color:#f2f6f6;margin-bottom:26px"><span style="color:#eda63a">shadow</span>price</div>
        <div style="background:#1e3038;border-radius:10px;padding:28px">${body}</div>
      </div>
    </body></html>`,
    { status, headers: HEADERS },
  )
}

export async function GET(req: NextRequest) {
  const email = req.nextUrl.searchParams.get('e') ?? ''
  const sig = req.nextUrl.searchParams.get('s') ?? ''
  if (!email || !verify(email, sig)) {
    return page(`<h2 style="margin:0 0 12px;font-size:20px;color:#f2f6f6">Link invalid.</h2>
      <p style="margin:0;font-size:14px;color:#93a6ab">Nothing was changed. Email team@shadowprice.io and we'll remove you by hand.</p>`, 400)
  }
  return page(
    `<h2 style="margin:0 0 12px;font-size:20px;color:#f2f6f6">Stop emailing ${email}?</h2>
     <p style="margin:0 0 20px;font-size:14px;color:#93a6ab">One click and you're off the list for good.</p>
     <form method="post" action="/api/unsubscribe">
       <input type="hidden" name="e" value="${email.replaceAll('"', '')}">
       <input type="hidden" name="s" value="${sig.replaceAll('"', '')}">
       <button type="submit" style="background:#eda63a;border:0;border-radius:6px;padding:12px 26px;font-size:14px;font-weight:700;color:#15242c;cursor:pointer">Unsubscribe</button>
     </form>`,
  )
}

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null)
  const email = String(form?.get('e') ?? '')
  const sig = String(form?.get('s') ?? '')
  if (!email || !verify(email, sig)) return page('<p style="color:#93a6ab">Link invalid — nothing changed.</p>', 400)
  const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!)
  const { error } = await sb.rpc('record_suppression', { p_email: email, p_server_secret: SECRET() })
  if (error) return page('<p style="color:#93a6ab">Something went wrong — email team@shadowprice.io and we\'ll remove you by hand.</p>', 500)
  return page(
    `<h2 style="margin:0 0 12px;font-size:20px;color:#f2f6f6">Done.</h2>
     <p style="margin:0;font-size:14px;color:#93a6ab">${email} won't hear from us again.</p>`,
  )
}
