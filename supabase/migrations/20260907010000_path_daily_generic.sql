-- Generic daily payoff series for any path/block/hedge in a given delivery
-- month — derived entirely from public settled prices; used by the method
-- progress screen's expandable daily charts. Authenticated members only.
create or replace function get_path_daily(
  p_src text, p_snk text, p_tou text, p_hedge text, p_month date)
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '30s'
as $$
  select coalesce((
    select jsonb_agg(jsonb_build_object(
             'd', d, 'hours', hrs, 'paid_per_mwh', paid_per_mwh) order by d)
      from (
        select src.delivery_date as d, count(*) as hrs,
               coalesce(sum(case when p_hedge = 'OPT'
                                 then greatest(k.price - src.price, 0)
                                 else k.price - src.price end), 0) as paid_per_mwh
          from dam_spp src
          join dam_spp k on k.interval_start = src.interval_start
         where src.settlement_point = p_src and k.settlement_point = p_snk
           and src.delivery_date >= date_trunc('month', p_month)::date
           and src.delivery_date < (date_trunc('month', p_month) + interval '1 month')::date
           and src.delivery_date <= current_date
           and (case when src.hour_ending between 7 and 22
                     then case when extract(isodow from src.delivery_date) < 6
                               then 'PeakWD' else 'PeakWE' end
                     else 'Off-peak' end) = p_tou
         group by src.delivery_date
      ) days), '[]'::jsonb)
  where auth.uid() is not null;
$$;
revoke execute on function get_path_daily(text, text, text, text, date) from public, anon;
grant execute on function get_path_daily(text, text, text, text, date) to authenticated;
