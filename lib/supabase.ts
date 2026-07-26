// Read-only Supabase access for the dashboard.
//
// This client uses the ANON key and reads through RLS. It must never be given
// the service-role key or DATABASE_URL — ingest owns those, and they live only
// on Render.

import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = process.env.NEXT_PUBLIC_SUPABASE_URL
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

export const supabaseConfigured = Boolean(url && anonKey)

/**
 * Null when the environment is not configured.
 *
 * Vercel builds this app before the Supabase project necessarily exists, so
 * throwing at module scope would fail the build rather than render an
 * explanatory empty state.
 */
export const supabase: SupabaseClient | null = supabaseConfigured
  ? createClient(url!, anonKey!, { auth: { persistSession: false } })
  : null

export interface Query<T> {
  rows: T[]
  error: string | null
}

const NOT_CONFIGURED =
  'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and ' +
  'NEXT_PUBLIC_SUPABASE_ANON_KEY in the Vercel project.'

/**
 * Run a read and return rows plus a message, never a throw.
 *
 * A monitoring page that 500s when the thing it monitors is down is worse than
 * useless, so every failure becomes visible text on the page instead.
 */
export async function query<T>(
  run: (client: SupabaseClient) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
): Promise<Query<T>> {
  if (!supabase) return { rows: [], error: NOT_CONFIGURED }
  try {
    const { data, error } = await run(supabase)
    if (error) return { rows: [], error: error.message }
    return { rows: data ?? [], error: null }
  } catch (cause) {
    return { rows: [], error: cause instanceof Error ? cause.message : String(cause) }
  }
}

// ------------------------------------------------------------------ shapes --

export interface LatestPrice {
  settlement_point: string
  interval_start: string
  price: number | string
  ingested_at: string
}

export interface RtPrice {
  settlement_point: string
  interval_start: string
  price: number | string
}

export interface FeedLatency {
  feed: string
  hour: string
  rows: number
  avg_lag_seconds: number | string | null
  last_ingest: string | null
}

export interface IngestRun {
  id: number
  job: string
  started_at: string
  finished_at: string | null
  status: 'running' | 'ok' | 'error' | 'empty'
  rows_seen: number
  rows_inserted: number
  rows_revised: number
  error: string | null
}

export interface SpikeRow {
  settlement_point: string
  interval_start: string
  spp_15min: number | string
  lmp_5min_avg: number | string | null
  lmp_5min_max: number | string | null
  lmp_5min_min: number | string | null
  lmp_5min_count: number | null
  spike_ratio: number | string | null
}

export interface RevisionCount {
  feed: string
  hour: string
  revisions: number
}
