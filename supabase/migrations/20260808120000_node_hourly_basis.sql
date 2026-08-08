-- Hourly node basis, computed once and maintained incrementally.
--
-- Every analysis script was rebuilding this from rt_spp — a 10GB, 72M-row
-- table — inside a temp table, five-plus times in a single day. That exhausted
-- the project's Disk IO budget and took the instance down. The data is
-- identical each time and only ever grows at the tail, so it belongs in a real
-- table refreshed forward, not a temp table rebuilt from zero.
--
-- basis = node price minus the system mean for that hour, which is the
-- quantity every exposure regression actually consumes.
create table if not exists node_hourly_basis (
  h                timestamptz not null,
  settlement_point text        not null,
  price            numeric     not null,
  basis            numeric     not null,
  primary key (h, settlement_point)
);

create index if not exists node_hourly_basis_sp_idx on node_hourly_basis (settlement_point, h);

alter table node_hourly_basis enable row level security;
drop policy if exists node_hourly_basis_read on node_hourly_basis;
create policy node_hourly_basis_read on node_hourly_basis for select using (true);
grant select on node_hourly_basis to anon, authenticated;

-- Refresh forward from the last stored hour. Bounded by design: pass a small
-- window and call it often rather than rebuilding history.
create or replace function refresh_node_hourly_basis(p_from timestamptz default null,
                                                     p_to   timestamptz default null)
returns bigint
language plpgsql
set search_path = public, pg_temp
as $$
declare
  lo timestamptz;
  hi timestamptz;
  n  bigint;
begin
  lo := coalesce(p_from, (select coalesce(max(h), '2024-07-01'::timestamptz)
                            from node_hourly_basis));
  hi := coalesce(p_to, lo + interval '45 days');

  with nb as (
    select date_trunc('hour', interval_start) hh, settlement_point sp, avg(price) p
      from rt_spp
     where interval_start >= lo and interval_start < hi
     group by 1, 2),
  sysm as (
    select hh, avg(p) m, count(*) k from nb group by 1)
  insert into node_hourly_basis (h, settlement_point, price, basis)
  select nb.hh, nb.sp, nb.p, nb.p - sysm.m
    from nb join sysm using (hh)
   where sysm.k > 400
  on conflict (h, settlement_point) do update
    set price = excluded.price, basis = excluded.basis;

  get diagnostics n = row_count;
  return n;
end $$;

grant execute on function refresh_node_hourly_basis(timestamptz, timestamptz)
  to anon, authenticated;
