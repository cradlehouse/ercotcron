-- Daily flow data for a sheet's traded rows: per path, the day-by-day payoff
-- series through the delivery month — the method-page flow chart's fuel.
-- Admin-gated alongside the progress ledger.
create or replace function get_sheet_flow(p_sheet text)
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '45s'
as $$
  with months as (
    select array['JAN','FEB','MAR','APR','MAY','JUN',
                 'JUL','AUG','SEP','OCT','NOV','DEC'] as m
  ),
  meta as (
    select make_date((substring(p_sheet from 4 for 4))::int,
                     array_position((select m from months),
                                    substring(p_sheet from 1 for 3)), 1) as m0
  ),
  rows_ as (
    select s.source, s.sink, s.time_of_use as tou, s.hedge_type as hedge,
           s.tier, s.filled, s.clearing as cp,
           coalesce(nullif(s.suggested_mw, 0), 1) as mw
      from sheet_snapshots s
     where s.sheet = p_sheet and s.clearing is not null
  )
  select jsonb_build_object(
    'month', to_char((select m0 from meta), 'YYYY-MM'),
    'rows', coalesce((
      select jsonb_agg(jsonb_build_object(
               'source', r.source, 'sink', r.sink, 'tou', r.tou,
               'hedge', r.hedge, 'tier', r.tier, 'filled', r.filled,
               'cp', r.cp, 'mw', r.mw, 'days', d.days))
        from rows_ r
        cross join lateral (
          select coalesce(jsonb_agg(jsonb_build_object(
                   'd', extract(day from dd)::int, 'hrs', hrs, 'ppm', ppm)
                 order by dd), '[]'::jsonb) as days
            from (
              select src.delivery_date as dd, count(*) as hrs,
                     round(coalesce(sum(case when r.hedge = 'OPT'
                                       then greatest(k.price - src.price, 0)
                                       else k.price - src.price end), 0)::numeric, 2) as ppm
                from dam_spp src
                join dam_spp k on k.interval_start = src.interval_start
               where src.settlement_point = r.source and k.settlement_point = r.sink
                 and src.delivery_date >= (select m0 from meta)
                 and src.delivery_date < (select m0 from meta) + interval '1 month'
                 and src.delivery_date <= current_date
                 and (case when src.hour_ending between 7 and 22
                           then case when extract(isodow from src.delivery_date) < 6
                                     then 'PeakWD' else 'PeakWE' end
                           else 'Off-peak' end) = r.tou
               group by src.delivery_date
            ) g
        ) d), '[]'::jsonb))
   where exists (select 1 from profiles
                  where user_id = auth.uid() and role = 'admin');
$$;
revoke execute on function get_sheet_flow(text) from public, anon;
grant execute on function get_sheet_flow(text) to authenticated;
