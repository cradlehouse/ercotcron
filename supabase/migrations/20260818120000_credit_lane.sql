-- Lane 3: credit seats. Admin-granted, per-counterparty, expiring, logged.
-- Separate grant table + separate function from the holder lane on purpose:
-- no shared code path between "my book" and "counterparty book".

alter table profiles add column if not exists role text not null default 'holder'
  check (role in ('holder','credit','admin'));

create table if not exists credit_grants (
  user_id           uuid not null references auth.users(id) on delete cascade,
  counterparty_code text not null,
  engagement_ref    text,                -- contract / engagement the grant hangs on
  granted_by        text not null,
  granted_at        timestamptz not null default now(),
  expires_at        timestamptz,         -- null = until revoked
  revoked_at        timestamptz,
  primary key (user_id, counterparty_code)
);
alter table credit_grants enable row level security;
drop policy if exists "own credit grants" on credit_grants;
create policy "own credit grants" on credit_grants
  for select using (auth.uid() = user_id);

-- Every cross-holder view is recorded. Append-only by trigger.
create table if not exists access_log (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  user_id     uuid not null,
  action      text not null,             -- 'counterparty-book'
  subject     text not null              -- the code viewed
);
alter table access_log enable row level security;  -- definer-only
create or replace function access_log_guard() returns trigger
language plpgsql set search_path = '' as $$
begin raise exception 'access_log is append-only'; end $$;
drop trigger if exists access_log_guard on access_log;
create trigger access_log_guard
  before update or delete on access_log
  for each row execute function access_log_guard();

create or replace function get_counterparty_book(p_code text)
returns table (
  source text, sink text, time_of_use text, hedge_type text,
  mw numeric, positions bigint, first_start date, last_end date,
  avg_clear numeric, tier text, margin_x numeric, warnings text
)
language plpgsql security definer set search_path = public as $$
begin
  p_code := upper(trim(p_code));
  if not exists (
    select 1 from credit_grants g
     where g.user_id = auth.uid() and g.counterparty_code = p_code
       and g.revoked_at is null
       and (g.expires_at is null or g.expires_at > now())
  ) then
    raise exception 'no active grant for this counterparty';
  end if;
  insert into access_log (user_id, action, subject)
  values (auth.uid(), 'counterparty-book', p_code);

  return query
  select a.source, a.sink, a.time_of_use, a.hedge_type,
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
    left join path_valuations v
      on v.source = a.source and v.sink = a.sink
     and v.time_of_use = a.time_of_use and v.hedge_type = a.hedge_type
   where a.account_holder = p_code and a.end_date >= now()::date
   group by a.source, a.sink, a.time_of_use, a.hedge_type,
            v.warnings, v.ceiling, v.cleared_price
   order by sum(a.mw) desc
   limit 500;
end $$;
revoke all on function get_counterparty_book(text) from public;
grant execute on function get_counterparty_book(text) to authenticated;
