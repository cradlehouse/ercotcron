-- Close the RLS gap on every table added after the original schema.
--
-- 20260726120300_rls.sql enabled row level security on the nine tables that
-- existed then. Every table created since — the CRR, fundamentals, weather and
-- bids migrations — granted select to anon and never enabled RLS. Grant without
-- RLS is not read-only: it leaves INSERT, UPDATE and DELETE open to anyone
-- holding the publishable key, which is public by design and ships to browsers.
--
-- Verified by probing PostgREST with a deliberately invalid payload: the nine
-- tables below returned 23502 (not-null violation — the write was permitted and
-- only failed on a constraint) where the original tables returned 42501
-- (permission denied). A well-formed insert would have landed.
--
-- The same pattern as the original: enable RLS, then a read-only policy per
-- table. Ingest is unaffected — it connects as the table-owning Postgres role
-- over a direct connection, which bypasses RLS.

do $$
declare
  t text;
begin
  foreach t in array array[
    'wind_power','solar_power','load_forecast','binding_constraints',
    'crr_auctions','crr_awards','crr_point_prices','crr_bids','weather_forecast'
  ] loop
    if to_regclass(t) is null then
      continue;
    end if;
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists %I on %I', t || '_read', t);
    execute format(
      'create policy %I on %I for select to anon, authenticated using (true)',
      t || '_read', t);
  end loop;
end $$;
