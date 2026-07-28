-- Re-stamped from 20260728180000 (this file replaces it in the same push —
-- the original never applied, so no version mismatch). Built WITH NO DATA: the
-- migration runner has its own statement timeout, and populating these against
-- 18M rows inside the migration rolled the whole file back. The service's
-- hourly signals job does the first populate over a direct connection, where
-- no anon-role timeout applies.
--
-- Materialise the scanner views: at 18M day-ahead rows they cannot be computed
-- per page load. Anon requests get a statement timeout of a few seconds, and
-- these views now join dam_spp against rt_spp with window functions — every
-- scanner panel timed out the moment real data volumes arrived. Same lesson as
-- crr_pnl: dashboard reads come from precomputed results, refreshed when the
-- data changes, not on request.
--
-- The z-score, node-hour and duration views are bounded to the tracked hubs
-- and zones INSIDE the definition — that is what the dashboard shows, and it
-- is what keeps the refresh fast enough to run hourly. Full-map versions are
-- reporting queries against the base tables.

drop view if exists spread_zscore;
drop view if exists node_hour_spread;
drop view if exists spread_duration;
drop view if exists basis_correlation;

create materialized view if not exists spread_zscore as
with tracked as (
  select name from settlement_points
  where name like 'HB\_%' or name like 'LZ\_%'
), hourly as (
  select d.settlement_point,
         d.interval_start,
         d.delivery_date,
         d.hour_ending,
         d.price                         as dam_price,
         avg(r.price)                    as rt_price,
         d.price - avg(r.price)          as spread
    from dam_spp d
    join rt_spp r
      on r.settlement_point = d.settlement_point
     and r.interval_start >= d.interval_start
     and r.interval_start <  d.interval_start + interval '1 hour'
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '120 days'
   group by d.settlement_point, d.interval_start, d.delivery_date,
            d.hour_ending, d.price
), scored as (
  select *,
         avg(spread) over w         as trailing_mean,
         stddev_samp(spread) over w as trailing_sd,
         count(*) over w            as trailing_n
    from hourly
  window w as (
    partition by settlement_point
    order by interval_start
    rows between 168 preceding and 1 preceding
  )
)
select settlement_point,
       interval_start,
       delivery_date,
       hour_ending,
       round(dam_price, 2)                    as dam_price,
       round(rt_price::numeric, 2)            as rt_price,
       round(spread::numeric, 2)              as spread,
       round(trailing_mean::numeric, 2)       as trailing_mean,
       round(trailing_sd::numeric, 2)         as trailing_sd,
       case when trailing_sd > 0 and trailing_n >= 48
            then round(((spread - trailing_mean) / trailing_sd)::numeric, 2)
       end                                    as z
  from scored
with no data;

create unique index if not exists spread_zscore_key
  on spread_zscore (settlement_point, interval_start);

create materialized view if not exists node_hour_spread as
with tracked as (
  select name from settlement_points
  where name like 'HB\_%' or name like 'LZ\_%'
), hourly as (
  select d.settlement_point,
         d.hour_ending,
         d.price - avg(r.price) as spread
    from dam_spp d
    join rt_spp r
      on r.settlement_point = d.settlement_point
     and r.interval_start >= d.interval_start
     and r.interval_start <  d.interval_start + interval '1 hour'
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '180 days'
   group by d.settlement_point, d.hour_ending, d.interval_start, d.price
)
select settlement_point,
       hour_ending,
       count(*)                                        as observations,
       round(avg(spread)::numeric, 3)                  as mean_spread,
       round(stddev_samp(spread)::numeric, 3)          as sd_spread,
       round((avg(spread) / nullif(stddev_samp(spread), 0)
              * sqrt(count(*)))::numeric, 2)           as t_stat,
       round(100.0 * count(*) filter (where spread > 0) / count(*), 0)
                                                       as pct_dam_over
  from hourly
 group by 1, 2
having count(*) >= 30
with no data;

create unique index if not exists node_hour_key
  on node_hour_spread (settlement_point, hour_ending);

create materialized view if not exists spread_duration as
with tracked as (
  select name from settlement_points
  where name like 'HB\_%' or name like 'LZ\_%'
), hourly as (
  select d.settlement_point,
         d.price - avg(r.price) as spread
    from dam_spp d
    join rt_spp r
      on r.settlement_point = d.settlement_point
     and r.interval_start >= d.interval_start
     and r.interval_start <  d.interval_start + interval '1 hour'
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '180 days'
   group by d.settlement_point, d.interval_start, d.price
)
select settlement_point,
       count(*)                                                          as hours,
       round(percentile_cont(0.01) within group (order by spread)::numeric, 2) as p01,
       round(percentile_cont(0.05) within group (order by spread)::numeric, 2) as p05,
       round(percentile_cont(0.25) within group (order by spread)::numeric, 2) as p25,
       round(percentile_cont(0.50) within group (order by spread)::numeric, 2) as p50,
       round(percentile_cont(0.75) within group (order by spread)::numeric, 2) as p75,
       round(percentile_cont(0.95) within group (order by spread)::numeric, 2) as p95,
       round(percentile_cont(0.99) within group (order by spread)::numeric, 2) as p99,
       round(avg(spread)::numeric, 2)                                    as mean,
       round((abs(percentile_cont(0.01) within group (order by spread))
              / nullif(percentile_cont(0.99) within group (order by spread), 0))::numeric, 2)
                                                                         as tail_ratio
  from hourly
 group by 1
having count(*) >= 100
with no data;

create unique index if not exists spread_duration_key
  on spread_duration (settlement_point);

create materialized view if not exists basis_correlation as
select a.settlement_point                         as point_a,
       b.settlement_point                         as point_b,
       count(*)                                   as hours,
       round(corr(a.price, b.price)::numeric, 3)  as correlation,
       round(avg(a.price - b.price)::numeric, 2)  as mean_basis,
       round(stddev_samp(a.price - b.price)::numeric, 2) as basis_sd
  from dam_spp a
  join dam_spp b
    on b.interval_start = a.interval_start
   and a.settlement_point < b.settlement_point
 where a.interval_start >= now() - interval '180 days'
   and (a.settlement_point like 'HB\_%' or a.settlement_point like 'LZ\_%')
   and (b.settlement_point like 'HB\_%' or b.settlement_point like 'LZ\_%')
 group by 1, 2
having count(*) >= 100
with no data;

create unique index if not exists basis_correlation_key
  on basis_correlation (point_a, point_b);

grant select on spread_zscore, node_hour_spread, spread_duration, basis_correlation
   to anon, authenticated;
