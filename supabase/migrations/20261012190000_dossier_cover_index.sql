-- Path dossier: stop timing out on a cold cache.
--
-- Measured 12 Oct 2026 on production: 249 of the 427 sheet paths took longer
-- than the 8s statement_timeout the authenticated role runs under (median
-- 9.5s), so most dossier pages failed for members. Every part of
-- get_path_dossier is sub-second except the payoffs join on dam_spp, which ran
-- 9.4s cold and 0.4s warm for the same path. The cause is physical layout:
-- dam_spp is written one interval at a time for ~1,100 points, so one point's
-- 25 months (~18k rows) sit on ~18k different heap pages (EXPLAIN: "Heap
-- Blocks: exact=18262" for 18,264 rows).
--
-- Fix, in three parts:
--   1. A covering index keyed (settlement_point, interval_start) that carries
--      every column the join reads, so both sides become index-only scans over
--      a few hundred contiguous index pages instead of ~18k heap pages.
--   2. get_path_dossier bounds interval_start, not only delivery_date, so the
--      index range itself is 25 months, not the point's whole history. The
--      delivery_date filter stays, so results are unchanged.
--   3. dam_spp had never been vacuumed (insert-only; the default insert
--      threshold is 20% of 17M rows), so ~15% of pages were not all-visible and
--      index-only scans would still visit the heap for recent rows. A lower
--      insert scale factor keeps the visibility map current; the VACUUM below
--      catches it up once.
--
-- CREATE INDEX CONCURRENTLY and VACUUM cannot run inside a transaction block:
-- run this file statement by statement (autocommit), not as one transaction.
-- CONCURRENTLY takes no lock that blocks ingest writes.

create index concurrently if not exists dam_spp_point_ts_cover_idx
  on dam_spp (settlement_point, interval_start)
  include (delivery_date, hour_ending, price);

alter table dam_spp set (autovacuum_vacuum_insert_scale_factor = 0.01);

vacuum (analyze) dam_spp;

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
          join dam_spp k on k.settlement_point = p_snk
                        and k.interval_start = s.interval_start
         where s.settlement_point = p_src
           -- index range (a day wider than the date filter, which still decides)
           and s.interval_start >= (current_date - interval '25 months' - interval '1 day')
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
$function$;
