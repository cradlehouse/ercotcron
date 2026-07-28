-- Rebuild the scanner matviews on top of rt_hourly.
--
-- 20260728190000 created these reading rt_spp directly and IS already applied,
-- so it cannot be edited — a recorded version with different content is what
-- broke the migration runner earlier today. This file supersedes it.
--
-- Each view previously re-grouped 7M+ real-time rows to hourly, three times
-- over. rt_hourly does that grouping once; these now read ~260k pre-grouped
-- rows and join on equality instead of a range predicate.

drop materialized view if exists spread_zscore;
drop materialized view if exists node_hour_spread;
drop materialized view if exists spread_duration;
drop materialized view if exists basis_correlation;

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
         r.price                         as rt_price,
         d.price - r.price               as spread
    from dam_spp d
    join rt_hourly r
      on r.settlement_point = d.settlement_point
     and r.hour_start       = d.interval_start
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '120 days'
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
         d.price - r.price as spread
    from dam_spp d
    join rt_hourly r
      on r.settlement_point = d.settlement_point
     and r.hour_start       = d.interval_start
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '180 days'
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
         d.price - r.price as spread
    from dam_spp d
    join rt_hourly r
      on r.settlement_point = d.settlement_point
     and r.hour_start       = d.interval_start
   where d.settlement_point in (select name from tracked)
     and d.interval_start >= now() - interval '180 days'
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
