-- Daily win/loss for one of the member's own in-delivery positions: per
-- settled day this month, hours banked, pro-rata cost, and payout. Ownership
-- enforced inside — the position must belong to the caller's APPROVED codes.
create or replace function get_position_daily(
  p_src text, p_snk text, p_tou text, p_hedge text)
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '30s'
as $$
  with mine as (
    select holder_code from user_holders
     where user_id = auth.uid() and status = 'approved'
  ),
  pos as (
    select round(avg(clearing_price)::numeric, 4) as cp,
           round(sum(mw)::numeric, 1) as mw
      from crr_awards
     where account_holder in (select holder_code from mine)
       and source = p_src and sink = p_snk
       and time_of_use = p_tou and hedge_type = p_hedge
       and current_date between start_date and end_date
    having count(*) > 0
  )
  select coalesce((
    select jsonb_agg(jsonb_build_object(
             'd', d, 'hours', hrs,
             'paid_in', round((p.cp * hrs * p.mw)::numeric, 0),
             'paid_out', round((paid_per_mwh * p.mw)::numeric, 0))
           order by d)
      from pos p
      cross join lateral (
        select src.delivery_date as d, count(*) as hrs,
               coalesce(sum(case when p_hedge = 'OPT'
                                 then greatest(k.price - src.price, 0)
                                 else k.price - src.price end), 0) as paid_per_mwh
          from dam_spp src
          join dam_spp k on k.interval_start = src.interval_start
         where src.settlement_point = p_src
           and k.settlement_point = p_snk
           and src.delivery_date >= date_trunc('month', current_date)::date
           and src.delivery_date <= current_date
           and (case when src.hour_ending between 7 and 22
                     then case when extract(isodow from src.delivery_date) < 6
                               then 'PeakWD' else 'PeakWE' end
                     else 'Off-peak' end) = p_tou
         group by src.delivery_date
      ) days
  ), '[]'::jsonb)
  where auth.uid() is not null;
$$;

revoke execute on function get_position_daily(text, text, text, text) from public, anon;
grant execute on function get_position_daily(text, text, text, text) to authenticated;
