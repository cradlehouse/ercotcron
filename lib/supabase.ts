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

export interface DartRow {
  settlement_point: string
  interval_start: string
  delivery_date: string
  hour_ending: number
  dam_price: number | string
  rt_avg: number | string
  rt_intervals: number
  spread: number | string
}

export interface BatteryArbRow {
  settlement_point: string
  delivery_date: string
  hours_observed: number
  charge_avg: number | string | null
  discharge_avg: number | string | null
  gross_per_mw: number | string | null
}

export interface ExtremesRow {
  settlement_point: string
  delivery_date: string
  intervals: number
  negative_intervals: number
  scarcity_intervals: number
  min_price: number | string
  max_price: number | string
  avg_price: number | string
}

export interface PathSpreadRow {
  point_a: string
  point_b: string
  hours: number
  avg_spread: number | string
  spread_sd: number | string | null
  pct_b_higher: number | string
  max_spread: number | string
  min_spread: number | string
  avg_abs_spread: number | string
}

export interface PathDartRow {
  point_a: string
  point_b: string
  hours: number
  avg_dam_spread: number | string
  avg_rt_spread: number | string
  avg_miss: number | string
  miss_sd: number | string | null
}

export interface PriceStackRow {
  bucket: number
  net_load_from: number | string
  net_load_to: number | string
  hours: number
  median_price: number | string
  p95_price: number | string
  avg_price: number | string
  pct_scarcity: number | string
  pct_negative: number | string
}

export interface WindSensitivityRow {
  hour_ending: number
  hours: number
  price_per_mw_wind: number | string | null
  r2: number | string | null
  correlation: number | string | null
  avg_wind_mw: number | string | null
  avg_price: number | string
}

export interface CrrEdgeRow {
  source: string
  sink: string
  time_of_use: string
  hedge_type: string
  auctions: number
  avg_cost_per_mwh: number | string
  avg_payoff_per_mwh: number | string
  avg_edge_per_mwh: number | string
  edge_sd: number | string | null
  t_stat: number | string | null
  net_total: number | string | null
  pct_profitable: number | string
}

export interface SpreadZRow {
  settlement_point: string
  interval_start: string
  hour_ending: number
  dam_price: number | string
  rt_price: number | string
  spread: number | string
  z: number | string | null
}

export interface NodeHourRow {
  settlement_point: string
  hour_ending: number
  observations: number
  mean_spread: number | string
  sd_spread: number | string | null
  t_stat: number | string | null
  pct_dam_over: number | string
}

export interface DurationRow {
  settlement_point: string
  hours: number
  p01: number | string
  p05: number | string
  p25: number | string
  p50: number | string
  p75: number | string
  p95: number | string
  p99: number | string
  mean: number | string
  tail_ratio: number | string | null
}

export interface ImpliedVolRow {
  source: string
  sink: string
  time_of_use: string
  auctions: number
  avg_premium: number | string
  premium_sd: number | string | null
  avg_premium_ratio: number | string | null
  avg_option_price: number | string
  avg_obligation_price: number | string
  total_mw: number | string
}

/** A path's realised worth versus what was bid — see app/bids. */
export interface PathValuation {
  book: string
  source: string
  sink: string
  time_of_use: string
  hedge_type: string
  mw: number | string | null
  bids: number | null
  bid_price: number | string | null
  value_mean: number | string | null
  value_median: number | string | null
  value_p05: number | string | null
  value_p95: number | string | null
  pct_hours_pos: number | string | null
  hours: number | null
  edge: number | string | null
  ceiling: number | string | null
  cleared_price: number | string | null
  trim_pct: number | string | null
  drivers: string | null
  warnings: string | null
  window_start: string | null
  window_end: string | null
  computed_at: string
}

export interface SettlementPoint {
  name: string
  active: boolean
}

// --- browser auth client (member area: session persists, unlike the
// read-only dashboard client above) ---
export const sb: SupabaseClient = createClient(url ?? '', anonKey ?? '')
