import type { NextConfig } from 'next'

// The dashboard is a pure read client: no API routes, no server secrets, no cron.
// Ingestion runs on Render; a Vercel cron here would double every ERCOT pull.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Nothing in this app is safe to cache: it is a live monitor.
  // Pages opt out individually via `export const dynamic = 'force-dynamic'`.
}

export default nextConfig
