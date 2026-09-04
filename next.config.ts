import type { NextConfig } from 'next'

// The dashboard is a pure read client: no API routes, no server secrets, no cron.
// Ingestion runs on Render; a Vercel cron here would double every ERCOT pull.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Nothing in this app is safe to cache: it is a live monitor.
  // Pages opt out individually via `export const dynamic = 'force-dynamic'`.
  async headers() {
    return [{
      source: '/(.*)',
      headers: [
        // Verification tokens ride in URLs — never leak them via Referer.
        { key: 'Referrer-Policy', value: 'no-referrer' },
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'X-Frame-Options', value: 'DENY' },
      ],
    }]
  },
}

export default nextConfig
