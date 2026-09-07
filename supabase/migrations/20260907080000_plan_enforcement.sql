-- Review ("do when there is a paying customer"): profiles.plan and
-- trial_ends were display-only — billing could not be enforced. One helper,
-- checked inside every member product RPC, so an expired trial stops at the
-- database no matter what the client renders. Admin and comp always pass;
-- account plumbing (my_claims, accept_terms, claim_holder) stays ungated.
create or replace function has_active_plan()
returns boolean language sql stable security definer set search_path = public as $fn$
  select exists (
    select 1 from profiles
     where user_id = auth.uid()
       and (role = 'admin'
            or plan in ('active', 'comp')
            or (plan = 'trial' and trial_ends >= current_date)));
$fn$;
revoke execute on function has_active_plan() from public, anon;
grant execute on function has_active_plan() to authenticated;


-- get_bid_sheet: session check -> active-plan check
CREATE OR REPLACE FUNCTION public.get_bid_sheet()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select jsonb_build_object(
    'valuations', coalesce((
      select jsonb_agg(to_jsonb(v)) from path_valuations v
       where v.book in ('Market', 'Discovery')
          or v.book in (select bh.book from book_holders bh
                          join user_holders uh on uh.holder_code = bh.holder_code
                         where uh.user_id = auth.uid()
                           and uh.status = 'approved')), '[]'::jsonb),
    'offered', coalesce((
      select jsonb_agg(jsonb_build_object(
        'source', o.source, 'sink', o.sink,
        'time_of_use', o.time_of_use, 'hedge_type', o.hedge_type, 'mw', o.mw))
      from (
        select source, sink, time_of_use, hedge_type, sum(mw) as mw
        from crr_offers
        where auction_name = (select max(auction_name) from crr_offers)
          and (source, sink, time_of_use, hedge_type) in
              (select source, sink, time_of_use, hedge_type from path_valuations)
        group by 1, 2, 3, 4
      ) o), '[]'::jsonb),
    'offers_auction', (select max(auction_name) from crr_offers),
    'points', coalesce((
      select jsonb_agg(jsonb_build_object('name', name, 'active', active))
      from settlement_points), '[]'::jsonb)
  )
  where has_active_plan();
$function$
;


-- get_path_dossier: session check -> active-plan check
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
  where has_active_plan();
$function$
;


-- get_running_month: session check -> active-plan check
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
   where has_active_plan();
$function$
;


-- get_position_daily: session check -> active-plan check
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
  where has_active_plan();
$function$
;


-- get_path_daily: session check -> active-plan check
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
  where has_active_plan();
$function$
;


-- get_path_day: session check -> active-plan check
CREATE OR REPLACE FUNCTION public.get_path_day(p_src text, p_snk text, p_tou text, p_hedge text, p_day date)
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select jsonb_build_object(
    'day', p_day,
    'tou', p_tou,
    'hours', coalesce((
      select jsonb_agg(jsonb_build_object(
               'he', he,
               'block', block,
               'collects', block = p_tou,
               'paid_per_mwh', round(paid::numeric, 2))
             order by he)
        from (
          select s.hour_ending as he,
                 crr_time_of_use(s.delivery_date, s.hour_ending) as block,
                 case when p_hedge = 'OPT'
                      then greatest(k.price - s.price, 0)
                      else k.price - s.price end as paid
            from dam_spp s
            join dam_spp k on k.interval_start = s.interval_start
           where s.settlement_point = p_src
             and k.settlement_point = p_snk
             and s.delivery_date = p_day
        ) t), '[]'::jsonb))
  where has_active_plan();
$function$
;


-- get_method_score: session check -> active-plan check
CREATE OR REPLACE FUNCTION public.get_method_score()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  where has_active_plan();
$function$
;
