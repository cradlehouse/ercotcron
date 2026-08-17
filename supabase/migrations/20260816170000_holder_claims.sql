-- Holder claims: users self-claim their CRRAH code at signup; claims are
-- pending until approved (per-holder data only to the verified holder).

alter table user_holders add column if not exists status text not null default 'pending'
  check (status in ('pending','approved','rejected'));

drop policy if exists "own claims" on user_holders;
create policy "own claims" on user_holders
  for insert with check (auth.uid() = user_id);

-- The member book: live positions for the caller's APPROVED holder codes,
-- aggregated per path and graded by the current valuation scan where the
-- path has been scored. SECURITY DEFINER so it can read crr_awards and
-- path_valuations regardless of table policies; the gate is the approved
-- claim check inside.
create or replace function get_my_book()
returns table (
  holder_code text, source text, sink text, time_of_use text, hedge_type text,
  mw numeric, positions bigint, first_start date, last_end date,
  avg_clear numeric, tier text, margin_x numeric, warnings text
)
language sql security definer set search_path = public as $$
  with mine as (
    select holder_code from user_holders
     where user_id = auth.uid() and status = 'approved')
  select a.account_holder, a.source, a.sink, a.time_of_use, a.hedge_type,
         sum(a.mw), count(*), min(a.start_date), max(a.end_date),
         round(avg(a.clearing_price), 4),
         case
           when v.warnings is not null then 'flagged'
           when v.ceiling is not null and v.cleared_price > 0
                and v.ceiling / v.cleared_price > 1.05 then 'good'
           when v.ceiling is not null then 'thin'
           else 'unscored'
         end,
         case when v.cleared_price > 0 then round(v.ceiling / v.cleared_price, 2) end,
         v.warnings
    from crr_awards a
    join mine m on m.holder_code = a.account_holder
    left join path_valuations v
      on v.source = a.source and v.sink = a.sink
     and v.time_of_use = a.time_of_use and v.hedge_type = a.hedge_type
   where a.end_date >= now()::date
   group by a.account_holder, a.source, a.sink, a.time_of_use, a.hedge_type,
            v.warnings, v.ceiling, v.cleared_price
   order by sum(a.mw) desc
   limit 500
$$;

revoke all on function get_my_book() from public;
grant execute on function get_my_book() to authenticated;
