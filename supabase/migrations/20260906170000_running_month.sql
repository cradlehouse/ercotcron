-- The running month: for the signed-in member's APPROVED holder codes, every
-- position currently in delivery with its banked hours, pro-rata cost, and
-- payout to date from settled day-ahead prices. Partial-month DESCRIPTION —
-- the official score still waits for the complete month (methodology §10).
create or replace function get_running_month()
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '30s'
as $$
  with mine as (
    select holder_code from user_holders
     where user_id = auth.uid() and status = 'approved'
  ),
  pos as (
    select source, sink, time_of_use, hedge_type,
           round(avg(clearing_price)::numeric, 4) as cp,
           round(sum(mw)::numeric, 1) as mw
      from crr_awards
     where account_holder in (select holder_code from mine)
       and current_date between start_date and end_date
     group by 1, 2, 3, 4
     order by abs(sum(mw * clearing_price)) desc
     limit 40
  ),
  scored as (
    select p.*, s.hrs, s.paid_per_mwh
      from pos p
      cross join lateral (
        select count(*) as hrs,
               coalesce(sum(case when p.hedge_type = 'OPT'
                                 then greatest(k.price - src.price, 0)
                                 else k.price - src.price end), 0) as paid_per_mwh
          from dam_spp src
          join dam_spp k on k.interval_start = src.interval_start
         where src.settlement_point = p.source
           and k.settlement_point = p.sink
           and src.delivery_date >= date_trunc('month', current_date)::date
           and src.delivery_date <= current_date
           and (case when src.hour_ending between 7 and 22
                     then case when extract(isodow from src.delivery_date) < 6
                               then 'PeakWD' else 'PeakWE' end
                     else 'Off-peak' end) = p.time_of_use
      ) s
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'source', source, 'sink', sink, 'tou', time_of_use, 'hedge', hedge_type,
           'mw', mw, 'cp', cp, 'hours', hrs,
           'paid_in', round((cp * hrs * mw)::numeric, 0),
           'paid_out', round((paid_per_mwh * mw)::numeric, 0))
         order by cp * hrs * mw desc), '[]'::jsonb)
    from scored
   where auth.uid() is not null;
$$;

revoke execute on function get_running_month() from public, anon;
grant execute on function get_running_month() to authenticated;
