-- Close the Supabase security advisor findings.
--
-- Measured exposure before this migration: the partitions flagged CRITICAL are
-- NOT reachable through PostgREST — it does not add partitions to its schema
-- cache, so requests return PGRST205. Writes to every base table were already
-- denied. So this is defence in depth rather than an open door. It still needs
-- doing: the moment a partition is exposed by some future config, or a limited
-- role connects directly, RLS is the only thing standing there.

-- ---------------------------------------------------------------- partitions
-- RLS on a partitioned parent governs access *through* the parent. Reaching a
-- partition directly bypasses it, so each partition needs its own policy.
do $$
declare r record;
begin
  for r in
    select c.relname
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'r'
       and c.relispartition and not c.relrowsecurity
  loop
    execute format('alter table public.%I enable row level security', r.relname);
    execute format('drop policy if exists %I on public.%I', r.relname || '_read', r.relname);
    execute format('create policy %I on public.%I for select using (true)',
                   r.relname || '_read', r.relname);
  end loop;
end $$;

-- New monthly partitions must arrive already protected, otherwise this
-- migration fixes today's ten and the eleventh reopens the gap.
create or replace function public.ensure_month_partition(p_table text, p_month date)
returns text
language plpgsql
set search_path = public, pg_temp
as $function$
declare
  start_ts date := date_trunc('month', p_month)::date;
  end_ts   date := (date_trunc('month', p_month) + interval '1 month')::date;
  part     text := format('%s_%s', p_table, to_char(start_ts, 'YYYYMM'));
begin
  if to_regclass(part) is null then
    execute format(
      'create table %I partition of %I for values from (%L) to (%L)',
      part, p_table, start_ts, end_ts);
    execute format('alter table %I enable row level security', part);
    execute format('create policy %I on %I for select using (true)',
                   part || '_read', part);
  end if;
  return part;
end $function$;

-- --------------------------------------------------------------------- views
-- A view without security_invoker runs as its owner, so it reads underlying
-- tables with the owner's rights and silently bypasses their RLS. Every base
-- table here grants select to anon and carries a permissive read policy, so
-- flipping these to invoker changes no result — it just stops the view being
-- a way around the policy if a table is ever restricted.
do $$
declare r record;
begin
  for r in
    select c.relname
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'v'
  loop
    execute format('alter view public.%I set (security_invoker = true)', r.relname);
  end loop;
end $$;

-- ----------------------------------------------------------------- functions
-- An unpinned search_path lets a caller who can create objects shadow the
-- names a function resolves. None of these are SECURITY DEFINER, so the blast
-- radius is small, but pinning costs nothing.
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'
       and coalesce(array_to_string(p.proconfig, ','), '') not like '%search_path%'
  loop
    execute format('alter function %s set search_path = public, pg_temp', r.sig);
  end loop;
end $$;

-- --------------------------------------------------------- materialized views
-- Left exposed deliberately. Materialized views cannot carry RLS at all, and
-- these hold derived public market data that the dashboard reads with the anon
-- key. Revoking select would break /scanner for no security gain, since every
-- underlying row is already readable. Recorded here so the advisor warning is
-- a known decision rather than an oversight.
