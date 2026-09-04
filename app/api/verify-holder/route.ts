// /api/verify-holder?token=... — the link sent to a holder's registered
// contact address. The token is the proof; no login required.
//
// GET renders a confirmation PAGE with a button; only the POST from that
// button approves. Corporate mail gateways (SafeLinks, Barracuda) prefetch
// every URL in inbound email — a bare GET-approves design let a bot silently
// consent on the holder's behalf. The human click is the consent record.
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

const HEADERS = {
  'Content-Type': 'text/html',
  'Referrer-Policy': 'no-referrer',
  'X-Robots-Tag': 'noindex',
}

function page(body: string, status = 200): NextResponse {
  return new NextResponse(
    `<!doctype html><html><body style="margin:0;background:#15242c;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif">
      <div style="max-width:520px;margin:14vh auto;padding:0 20px">
        <div style="font-size:17px;font-weight:700;letter-spacing:-0.01em;color:#f2f6f6;margin-bottom:26px"><span style="color:#eda63a">shadow</span>price</div>
        <div style="background:#1e3038;border-radius:10px;padding:28px">${body}</div>
        <div style="margin-top:16px;font-size:11px;color:#61767e">— The Shadowprice team · we hold no CRR positions</div>
      </div>
    </body></html>`,
    { status, headers: HEADERS },
  )
}

const KICKER = `<div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#93a6ab;margin-bottom:10px">Access request</div>`

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get('token') ?? ''
  if (!token) {
    return page(
      `${KICKER}<h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Link invalid.</h2>
       <p style="margin:0;font-size:14px;line-height:1.6;color:#93a6ab">Nothing was changed.</p>`,
      400,
    )
  }
  // No database write here — this page only asks for the click.
  return page(
    `${KICKER}<h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Confirm access to this CRR account?</h2>
     <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#93a6ab">
       Someone signed up on Shadowprice and asked to see this account&rsquo;s book, graded —
       an email to the account&rsquo;s registered ERCOT contact (you) is how we check that
       request is authorized. Confirming shows the book to that requester and nobody else.
       If this wasn&rsquo;t authorized by you, close this page and nothing changes.
     </p>
     <form method="post" action="/api/verify-holder">
       <input type="hidden" name="token" value="${token.replaceAll('"', '')}">
       <button type="submit" style="background:#eda63a;border:0;border-radius:6px;padding:12px 26px;font-size:14px;font-weight:700;color:#15242c;cursor:pointer">Confirm access</button>
     </form>`,
  )
}

export async function POST(req: NextRequest) {
  const form = await req.formData().catch(() => null)
  const token = String(form?.get('token') ?? '')
  const sb = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )
  const { data, error } = await sb.rpc('confirm_holder', { p_token: token })
  const ok = !error && data === 'approved'
  if (ok) {
    return page(
      `${KICKER}<h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Access confirmed.</h2>
       <p style="margin:0;font-size:14px;line-height:1.6;color:#93a6ab">The claim on this CRR account is approved. The requester can now see the book, graded, at <a href="https://shadowprice.io/app" style="color:#eda63a">shadowprice.io</a>.</p>`,
    )
  }
  return page(
    `${KICKER}<h2 style="margin:0 0 12px;font-size:22px;color:#f2f6f6">Link invalid or expired.</h2>
     <p style="margin:0;font-size:14px;line-height:1.6;color:#93a6ab">Nothing was changed. Claims can be re-requested from the member area at <a href="https://shadowprice.io/app" style="color:#eda63a">shadowprice.io</a>.</p>`,
    400,
  )
}
