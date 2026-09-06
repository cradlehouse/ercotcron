-- Admin: running progress of every pre-auction estimate that would have
-- filled — cost vs paid-out on settled days so far, across all sheets.
-- Red rows ride per-MW (suggested_mw 0 → effective 1), same as scoring.
create or replace function get_method_progress()
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '30s'
as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'sheet', sheet, 'source', source, 'sink', sink,
           'tou', time_of_use, 'hedge', hedge_type, 'tier', tier,
           'ref_limit', ref_limit, 'clearing', clearing,
           'mw', eff_mw, 'hours', hrs,
           'cost', round((clearing * hrs * eff_mw)::numeric, 0),
           'paid', round((paid_per_mwh * eff_mw)::numeric, 0))
         order by sheet, tier, paid_per_mwh * eff_mw desc), '[]'::jsonb)
    from (
      select s.*, coalesce(nullif(s.suggested_mw, 0), 1) as eff_mw,
             d.hrs, d.paid_per_mwh,
             substring(s.sheet from 1 for 3) as mon3,
             (substring(s.sheet from 4 for 4))::int as yr
        from sheet_snapshots s
        cross join lateral (
          select make_date((substring(s.sheet from 4 for 4))::int,
                           array_position(array['JAN','FEB','MAR','APR','MAY','JUN',
                                                'JUL','AUG','SEP','OCT','NOV','DEC'],
                                          substring(s.sheet from 1 for 3)), 1) as m0
        ) mm
        cross join lateral (
          select count(*) as hrs,
                 coalesce(sum(case when s.hedge_type = 'OPT'
                                   then greatest(k.price - src.price, 0)
                                   else k.price - src.price end), 0) as paid_per_mwh
            from dam_spp src
            join dam_spp k on k.interval_start = src.interval_start
           where src.settlement_point = s.source and k.settlement_point = s.sink
             and src.delivery_date >= mm.m0
             and src.delivery_date < mm.m0 + interval '1 month'
             and src.delivery_date <= current_date
             and (case when src.hour_ending between 7 and 22
                       then case when extract(isodow from src.delivery_date) < 6
                                 then 'PeakWD' else 'PeakWE' end
                       else 'Off-peak' end) = s.time_of_use
        ) d
       where s.filled and s.clearing is not null
    ) t
   where exists (select 1 from profiles
                  where user_id = auth.uid() and role = 'admin');
$$;
revoke execute on function get_method_progress() from public, anon;
grant execute on function get_method_progress() to authenticated;
