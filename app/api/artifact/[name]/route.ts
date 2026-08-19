// GET /api/artifact/[name] — serve platform-generated JSON from the artifacts
// table. Replaces JSON files committed to the repo: builders run on Render,
// write to Postgres, and the web reads here. Names are allow-listed.
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

const PUBLIC_ARTIFACTS = new Set(['node_graph', 'grid_geo', 'strip_2028'])

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params
  if (!PUBLIC_ARTIFACTS.has(name)) {
    return NextResponse.json({ error: 'unknown artifact' }, { status: 404 })
  }
  const sb = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  )
  const { data, error } = await sb.from('artifacts')
    .select('body, updated_at').eq('name', name).single()
  if (error || !data) {
    return NextResponse.json({ error: 'not found' }, { status: 404 })
  }
  return NextResponse.json(data.body, {
    headers: {
      'Cache-Control': 'public, max-age=300, stale-while-revalidate=3600',
      'X-Artifact-Updated': String(data.updated_at),
    },
  })
}
