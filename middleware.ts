// Password gate for the whole dashboard.
//
// The repo is public and the pages show a real account's bid prices, so the
// gate DENIES when no password is configured rather than failing open. Set
// DASH_PASSWORD in Vercel (and .env locally); any username works, the
// password is what's checked. HTTP Basic keeps it dependency-free and the
// browser remembers it for the session.

import { NextRequest, NextResponse } from 'next/server'

export function middleware(req: NextRequest) {
  const expected = process.env.DASH_PASSWORD
  if (!expected) {
    return new NextResponse(
      'Dashboard locked: DASH_PASSWORD is not configured in this environment.',
      { status: 401 },
    )
  }
  const header = req.headers.get('authorization') ?? ''
  if (header.startsWith('Basic ')) {
    try {
      const decoded = atob(header.slice(6))
      const password = decoded.slice(decoded.indexOf(':') + 1)
      if (password === expected) return NextResponse.next()
    } catch {
      // fall through to the challenge
    }
  }
  return new NextResponse('Authentication required', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="ercotcron"' },
  })
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
