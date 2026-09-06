-- Admin progress, unified: sheet-snapshot counterfactuals AND paper batches
-- (SEP / OCT / 2028 / ...). Paper rows: pending until results post; filled
-- rows show running cost vs paid on settled days; future deliveries (2028)
-- show as waiting.
create or replace function get_method_progress()
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '45s'
as $$
  with months as (
    select array['JAN','FEB','MAR','APR','MAY','JUN',
                 'JUL','AUG','SEP','OCT','NOV','DEC'] as m
  ),
  sheet_rows as (
    select s.sheet as grp, s.source, s.sink, s.time_of_use as tou,
           s.hedge_type as hedge, s.tier,
           s.ref_limit as bid, s.clearing as cp,
           coalesce(nullif(s.suggested_mw, 0), 1) as mw,
           make_date((substring(s.sheet from 4 for 4))::int,
                     array_position((select m from months),
                                    substring(s.sheet from 1 for 3)), 1) as m0,
           true as filled
      from sheet_snapshots s
     where s.filled and s.clearing is not null
  ),
  paper_rows as (
    select 'paper: ' || b.batch_id as grp, b.source, b.sink,
           b.time_of_use as tou, b.hedge_type as hedge,
           case when b.cleared is null then 'pending'
                when b.cleared then 'filled' else 'missed' end as tier,
           b.bid_price as bid, b.clearing_price as cp, b.mw::numeric as mw,
           coalesce(b.delivery_month,
                    make_date((substring(b.auction_name from 4 for 4))::int,
                              array_position((select m from months),
                                             substring(b.auction_name from 1 for 3)), 1)) as m0,
           coalesce(b.cleared, false) as filled
      from paper_bids b
  ),
  unioned as (
    select * from sheet_rows union all select * from paper_rows
  ),
  running as (
    select u.*,
           case when u.filled and u.m0 <= current_date then d.hrs else 0 end as hrs,
           case when u.filled and u.m0 <= current_date then d.paid_per_mwh else 0 end as paid_per_mwh
      from unioned u
      left join lateral (
        select count(*) as hrs,
               coalesce(sum(case when u.hedge = 'OPT'
                                 then greatest(k.price - src.price, 0)
                                 else k.price - src.price end), 0) as paid_per_mwh
          from dam_spp src
          join dam_spp k on k.interval_start = src.interval_start
         where u.filled and u.m0 <= current_date
           and src.settlement_point = u.source and k.settlement_point = u.sink
           and src.delivery_date >= u.m0
           and src.delivery_date < u.m0 + interval '1 month'
           and src.delivery_date <= current_date
           and (case when src.hour_ending between 7 and 22
                     then case when extract(isodow from src.delivery_date) < 6
                               then 'PeakWD' else 'PeakWE' end
                     else 'Off-peak' end) = u.tou
      ) d on true
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'grp', grp, 'source', source, 'sink', sink, 'tou', tou,
           'hedge', hedge, 'tier', tier, 'bid', bid, 'clearing', cp,
           'mw', mw, 'delivery', to_char(m0, 'YYYY-MM'),
           'status', case
             when tier = 'pending' then 'awaiting results'
             when not filled then 'missed'
             when m0 > current_date then 'awaiting delivery'
             else 'running' end,
           'hours', hrs,
           'cost', case when filled and m0 <= current_date and cp is not null
                        then round((cp * hrs * mw)::numeric, 0) end,
           'paid', case when filled and m0 <= current_date
                        then round((paid_per_mwh * mw)::numeric, 0) end)
         order by grp, tier, paid_per_mwh * mw desc), '[]'::jsonb)
    from running
   where exists (select 1 from profiles
                  where user_id = auth.uid() and role = 'admin');
$$;
revoke execute on function get_method_progress() from public, anon;
grant execute on function get_method_progress() to authenticated;
