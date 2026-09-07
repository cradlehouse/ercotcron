// Thin typed wrapper over the member-area Supabase RPC calls.
//
// Callers deal in `data` (typed) plus a plain error message string — no
// Postgrest error object plumbing repeated on every page.

import { sb } from './supabase'

export async function rpc<T>(
  fn: string,
  args?: Record<string, unknown>,
): Promise<{ data: T | null; error: string | null }> {
  const { data, error } = await sb.rpc(fn, args)
  return { data: (data as T | null) ?? null, error: error?.message ?? null }
}
