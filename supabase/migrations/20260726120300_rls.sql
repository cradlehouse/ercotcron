-- Row level security.
--
-- Ingest connects as the Postgres role over a direct connection and bypasses
-- RLS. The dashboard connects with the anon key through PostgREST and gets
-- read-only access — which is why no service-role key is deployed to Vercel.

alter table settlement_points  enable row level security;
alter table ingest_runs        enable row level security;
alter table dam_spp            enable row level security;
alter table dam_spp_history    enable row level security;
alter table rt_spp             enable row level security;
alter table rt_spp_history     enable row level security;
alter table rt_lmp_5min        enable row level security;
alter table rt_lmp_5min_history enable row level security;
alter table rtd_lmp            enable row level security;

do $$
declare
  t text;
begin
  foreach t in array array[
    'settlement_points','ingest_runs','dam_spp','dam_spp_history','rt_spp',
    'rt_spp_history','rt_lmp_5min','rt_lmp_5min_history','rtd_lmp'
  ] loop
    execute format('drop policy if exists %I on %I', t || '_read', t);
    execute format(
      'create policy %I on %I for select to anon, authenticated using (true)',
      t || '_read', t);
  end loop;
end $$;

-- Views run as their owner; grant the read roles explicit select on them.
grant select on feed_latency, revision_counts, rt_spp_gaps, spp_vs_lmp_5min,
                latest_prices
   to anon, authenticated;

grant execute on function rt_spp_asof(timestamptz, timestamptz, timestamptz),
                          dam_spp_asof(timestamptz, timestamptz, timestamptz),
                          lmp5_asof(timestamptz, timestamptz, timestamptz)
   to anon, authenticated;
