-- Sep 2026 review #5: the two public scorers disagreed on holidays —
-- score_paper applied NERC holidays, every SQL TOU classification was
-- weekday-only (Labor Day scored PeakWD). One calendar now:
--   Python: ercot/calendar.py    SQL: nerc_holiday(date) + crr_time_of_use()
-- crr_time_of_use becomes holiday-aware and every function that inlined its
-- own weekday-only case now calls it. Function bodies below are re-emitted
-- from prod 2026-09-07 with ONLY the TOU expression swapped.

-- Observed NERC holidays: New Year's, Memorial, July 4, Labor,
-- Thanksgiving, Christmas; Sunday holidays observed the following Monday,
-- Saturday holidays NOT substituted (NERC rule, not the federal one).
create or replace function nerc_holiday(p_date date)
returns boolean language sql immutable as $fn$
  with y as (select extract(year from p_date)::int as yr)
  select p_date in (
    select case when extract(isodow from d) = 7 then d + 1 else d end
      from y, unnest(array[
        make_date(yr, 1, 1), make_date(yr, 7, 4), make_date(yr, 12, 25)
      ]) d
    union all
    select d from y, lateral (values
      -- Memorial Day: last Monday of May
      (make_date(yr, 5, 31) - ((extract(isodow from make_date(yr, 5, 31))::int - 1) % 7)),
      -- Labor Day: first Monday of September
      (make_date(yr, 9, 1) + ((8 - extract(isodow from make_date(yr, 9, 1))::int) % 7)),
      -- Thanksgiving: fourth Thursday of November
      (make_date(yr, 11, 1) + ((11 - extract(isodow from make_date(yr, 11, 1))::int) % 7) + 21)
    ) t(d)
  );
$fn$;

create or replace function crr_time_of_use(p_date date, p_hour_ending int)
returns text language sql immutable as $fn$
  select case
    when p_hour_ending < 7 or p_hour_ending > 22 then 'Off-peak'
    when extract(isodow from p_date) <= 5 and not nerc_holiday(p_date) then 'PeakWD'
    else 'PeakWE'
  end;
$fn$;


-- get_path_dossier: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_path_dossier(p_src text, p_snk text)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select jsonb_build_object(
    'awards', coalesce((
      select jsonb_agg(jsonb_build_object(
               'auction', auction, 'tou', tou, 'hedge', hedge, 'cp', cp,
               'mw', mw, 'holders', holders, 'start', s, 'end', e)
             order by s, auction)
        from (select auction_name auction, time_of_use tou, hedge_type hedge,
                     round(avg(clearing_price)::numeric, 4) cp,
                     round(sum(mw)::numeric, 1) mw,
                     count(distinct account_holder) holders,
                     min(start_date) s, max(end_date) e
                from crr_awards
               where source = p_src and sink = p_snk
               group by 1, 2, 3) a), '[]'::jsonb),
    'payoffs', coalesce((
      with hours as (
        select s.delivery_date, s.hour_ending,
               (k.price - s.price) as diff
          from dam_spp s
          join dam_spp k on k.interval_start = s.interval_start
         where s.settlement_point = p_src and k.settlement_point = p_snk
           and s.delivery_date >= (current_date - interval '25 months')
      )
      select jsonb_agg(jsonb_build_object(
               'm', m, 'tou', tou, 'obl', obl, 'opt', opt, 'hours', h)
             order by m) from (
        select to_char(delivery_date, 'YYYY-MM') m,
               crr_time_of_use(delivery_date, hour_ending) tou,
               round(avg(diff)::numeric, 4) obl,
               round(avg(greatest(diff, 0))::numeric, 4) opt,
               count(*) h
          from hours
         group by 1, 2
      ) g), '[]'::jsonb),
    'offers', coalesce((
      select jsonb_agg(jsonb_build_object(
               'auction', auction, 'tou', tou, 'hedge', hedge,
               'mw', mw, 'min_ask', ask) order by auction)
        from (select auction_name auction, time_of_use tou, hedge_type hedge,
                     round(sum(mw)::numeric, 1) mw,
                     round(min(min_price)::numeric, 4) ask
                from crr_offers
               where source = p_src and sink = p_snk
               group by 1, 2, 3) o), '[]'::jsonb),
    'valuations', coalesce((
      select jsonb_agg(to_jsonb(v))
        from (select book, time_of_use, hedge_type, value_mean, value_typical,
                     ceiling, cleared_price, trim_pct, warnings, window_end
                from path_valuations
               where source = p_src and sink = p_snk
                 and book in ('Market', 'Discovery')) v), '[]'::jsonb),
    'paper', coalesce((
      select jsonb_agg(jsonb_build_object(
               'batch', batch_id, 'auction', auction_name, 'tou', time_of_use,
               'hedge', hedge_type, 'mw', mw, 'bid', bid_price,
               'cleared', cleared, 'cp', clearing_price, 'pnl', pnl)
             order by submitted_at)
        from paper_bids
       where source = p_src and sink = p_snk), '[]'::jsonb)
  )
  where auth.uid() is not null;
$function$
;


-- get_position_daily: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_position_daily(p_src text, p_snk text, p_tou text, p_hedge text)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
 SET statement_timeout TO '30s'
AS $function$
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
           and crr_time_of_use(src.delivery_date, src.hour_ending) = p_tou
         group by src.delivery_date
      ) days
  ), '[]'::jsonb)
  where auth.uid() is not null;
$function$
;


-- get_running_month: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_running_month()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
 SET statement_timeout TO '30s'
AS $function$
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
           and crr_time_of_use(src.delivery_date, src.hour_ending) = p.time_of_use
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
$function$
;


-- get_method_progress: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_method_progress()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
 SET statement_timeout TO '45s'
AS $function$
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
           s.filled
      from sheet_snapshots s
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
           case when u.cp is not null and u.m0 <= current_date then d.hrs else 0 end as hrs,
           case when u.cp is not null and u.m0 <= current_date then d.paid_per_mwh else 0 end as paid_per_mwh
      from unioned u
      left join lateral (
        select count(*) as hrs,
               coalesce(sum(case when u.hedge = 'OPT'
                                 then greatest(k.price - src.price, 0)
                                 else k.price - src.price end), 0) as paid_per_mwh
          from dam_spp src
          join dam_spp k on k.interval_start = src.interval_start
         where u.cp is not null and u.m0 <= current_date
           and src.settlement_point = u.source and k.settlement_point = u.sink
           and src.delivery_date >= u.m0
           and src.delivery_date < u.m0 + interval '1 month'
           and src.delivery_date <= current_date
           and crr_time_of_use(src.delivery_date, src.hour_ending) = u.tou
      ) d on true
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'grp', grp, 'source', source, 'sink', sink, 'tou', tou,
           'hedge', hedge, 'tier', tier, 'bid', bid, 'clearing', cp,
           'mw', mw, 'delivery', to_char(m0, 'YYYY-MM'),
           'status', case
             when tier = 'pending' then 'awaiting results'
             when cp is null and grp not like 'paper:%' then 'never traded'
             when m0 > current_date then case when filled then 'awaiting delivery' else 'missed' end
             when filled then 'running'
             else 'missed — market''s buy' end,
           'hours', hrs,
           'cost', case when cp is not null and m0 <= current_date
                        then round((cp * hrs * mw)::numeric, 0) end,
           'paid', case when cp is not null and m0 <= current_date
                        then round((paid_per_mwh * mw)::numeric, 0) end)
         order by grp, tier, paid_per_mwh * mw desc), '[]'::jsonb)
    from running
   where exists (select 1 from profiles
                  where user_id = auth.uid() and role = 'admin');
$function$
;


-- get_path_daily: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_path_daily(p_src text, p_snk text, p_tou text, p_hedge text, p_month date)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
 SET statement_timeout TO '30s'
AS $function$
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
           and crr_time_of_use(src.delivery_date, src.hour_ending) = p_tou
         group by src.delivery_date
      ) days), '[]'::jsonb)
  where auth.uid() is not null;
$function$
;


-- get_sheet_flow: TOU expression -> crr_time_of_use (1 site(s))
CREATE OR REPLACE FUNCTION public.get_sheet_flow(p_sheet text)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
 SET statement_timeout TO '45s'
AS $function$
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
                 and crr_time_of_use(src.delivery_date, src.hour_ending) = r.tou
               group by src.delivery_date
            ) g
        ) d), '[]'::jsonb))
   where exists (select 1 from profiles
                  where user_id = auth.uid() and role = 'admin');
$function$
;
