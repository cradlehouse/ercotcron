-- Method scoring: every published sheet is SNAPSHOTTED at publish (identity
-- columns immutable), then scored as results and settlement arrive — the
-- full-method counterfactual, not just the hand-picked paper batches.
-- Includes red rows (suggested_mw 0): the don't-bid calls get graded too.
create table if not exists sheet_snapshots (
  id bigint generated always as identity primary key,
  sheet text not null,                -- e.g. 'OCT2026Monthly'
  snapshot_at timestamptz not null default now(),
  source text not null, sink text not null,
  time_of_use text not null, hedge_type text not null,
  book text not null,
  tier text not null,                 -- green / amber / red
  ref_limit numeric,                  -- the reference limit as displayed
  suggested_mw numeric,               -- the uniform default size shown
  typical numeric, worth numeric, cleared_basis numeric,
  -- scoring columns (the only mutable ones):
  clearing numeric, filled boolean,
  hours int, cost numeric, realized numeric, pnl numeric,
  scored_at timestamptz
);
create index if not exists sheet_snapshots_sheet_idx on sheet_snapshots (sheet);
alter table sheet_snapshots enable row level security;
revoke all on sheet_snapshots from anon, authenticated;

create or replace function sheet_snapshots_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'sheet_snapshots is append-only';
  end if;
  if new.sheet <> old.sheet or new.source <> old.source or new.sink <> old.sink
     or new.time_of_use <> old.time_of_use or new.hedge_type <> old.hedge_type
     or new.tier <> old.tier
     or new.ref_limit is distinct from old.ref_limit
     or new.suggested_mw is distinct from old.suggested_mw then
    raise exception 'sheet_snapshots: sheet rows are immutable; only scoring columns may change';
  end if;
  return new;
end $$;
drop trigger if exists sheet_snapshots_guard on sheet_snapshots;
create trigger sheet_snapshots_guard
  before update or delete on sheet_snapshots
  for each row execute function sheet_snapshots_guard();

-- ---- Snapshot the OCT sheet from the live valuations, replicating the
-- ticket's own derivation (margin limit, lottery cap, tiering, sizing).
insert into sheet_snapshots
  (sheet, source, sink, time_of_use, hedge_type, book, tier,
   ref_limit, suggested_mw, typical, worth, cleared_basis)
select 'OCT2026Monthly', v.source, v.sink, v.time_of_use, v.hedge_type, v.book,
       case
         when v.value_mean is null or v.ceiling is null then 'red'
         when d.ref < 0.1 then 'red'
         when v.cleared_price is not null and v.cleared_price > 0
              and d.ref / v.cleared_price <= 1.0 then 'red'
         when v.book = 'Market' then 'amber'
         when v.cleared_price is not null and v.warnings is null
              and v.cleared_price > 0 and d.ref / v.cleared_price > 1.05
              and (coalesce(v.cleared_price, d.ref) < 0.75
                   or (coalesce(v.cleared_price, d.ref) <= 5
                       and d.ref / v.cleared_price >= 2.0)) then 'green'
         else 'amber'
       end,
       d.ref,
       case
         when v.value_mean is null or v.ceiling is null or d.ref < 0.1
              or (v.cleared_price is not null and v.cleared_price > 0
                  and d.ref / v.cleared_price <= 1.0) then 0
         when v.book not in ('Market', 'Discovery')
              then greatest(1, least(50, round(coalesce(v.mw, 1))))
         else greatest(1, least(
                floor(250.0 / greatest(
                  (case v.time_of_use when 'PeakWD' then 352
                                      when 'PeakWE' then 144 else 248 end)
                  * coalesce(nullif(v.cleared_price, 0), d.ref, 0.1), 1)),
                greatest(floor(coalesce(v.mw, 10) / 2), 1), 200))
       end,
       v.value_typical, v.value_mean, v.cleared_price
  from path_valuations v
  cross join lateral (
    select case when v.book in ('Market', 'Discovery')
                     and v.cleared_price is not null and v.cleared_price < 0.5
                then least(v.ceiling / 1.5, greatest(3 * v.cleared_price, 0.1))
                else v.ceiling / 1.5 end as ref
  ) d
 where v.book in ('Market', 'Discovery')
   and not exists (select 1 from sheet_snapshots s where s.sheet = 'OCT2026Monthly');

-- ---- Admin read: the method scorecard, aggregated per sheet and tier.
create or replace function get_method_score()
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'sheets', coalesce((
      select jsonb_agg(jsonb_build_object(
               'sheet', sheet, 'tier', tier, 'rows', n, 'snapshot_at', snap,
               'filled', filled_n, 'cost', cost, 'realized', realized, 'pnl', pnl)
             order by sheet, tier)
        from (select sheet, tier, count(*) n, min(snapshot_at)::date snap,
                     count(*) filter (where filled) filled_n,
                     round(sum(cost)::numeric, 0) cost,
                     round(sum(realized)::numeric, 0) realized,
                     round(sum(pnl)::numeric, 0) pnl
                from sheet_snapshots group by 1, 2) t), '[]'::jsonb),
    'rows', coalesce((
      select jsonb_agg(to_jsonb(r) order by r.sheet, r.tier, r.ref_limit desc)
        from (select sheet, source, sink, time_of_use, hedge_type, tier,
                     ref_limit, suggested_mw, clearing, filled, cost,
                     realized, pnl
                from sheet_snapshots
               order by sheet, tier, ref_limit desc
               limit 600) r), '[]'::jsonb))
  where exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'admin');
$$;
revoke execute on function get_method_score() from public, anon;
grant execute on function get_method_score() to authenticated;
