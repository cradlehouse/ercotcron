-- Bound the analytic views to recent windows.
--
-- These were written against a database holding one day of data and were
-- unbounded, which was invisible until the backfill took rt_spp from 1,200 rows
-- to 1,050,000. A full self-join across two years then exceeds PostgREST's
-- statement timeout and the page fails outright.
--
-- The windows below are chosen so each view answers its question over a period
-- a trader would actually look at, not so it merely finishes. Anything needing
-- the full history is a reporting query, not a dashboard view, and should read
-- the tables directly.

-- 30 days: a DART desk cares about the recent regime, and the join is against
-- every 15-minute interval, so this is the heaviest view per day of window.
create or replace view dart_spread as
select d.settlement_point,
       d.interval_start,
       d.delivery_date,
       d.hour_ending,
       d.price               as dam_price,
       round(r.rt_avg, 4)    as rt_avg,
       r.rt_intervals,
       round(r.rt_avg - d.price, 4) as spread
  from dam_spp d
  join (
    select settlement_point,
           date_trunc('hour', interval_start) as hour_start,
           avg(price) as rt_avg,
           count(*)   as rt_intervals
      from rt_spp
     where interval_start >= now() - interval '30 days'
     group by 1, 2
  ) r
    on r.settlement_point = d.settlement_point
   and r.hour_start       = d.interval_start
 where d.interval_start >= now() - interval '30 days';

create or replace view daily_battery_arb as
with hourly as (
  select settlement_point,
         delivery_date,
         date_trunc('hour', interval_start) as hour_start,
         avg(price) as price
    from rt_spp
   where interval_start >= now() - interval '90 days'
   group by 1, 2, 3
), ranked as (
  select *,
         row_number() over (partition by settlement_point, delivery_date
                            order by price desc) as hi,
         row_number() over (partition by settlement_point, delivery_date
                            order by price asc)  as lo
    from hourly
)
select settlement_point,
       delivery_date,
       count(*)                                          as hours_observed,
       round(avg(price) filter (where lo <= 2), 2)       as charge_avg,
       round(avg(price) filter (where hi <= 2), 2)       as discharge_avg,
       round((avg(price) filter (where hi <= 2)
            - avg(price) filter (where lo <= 2)) * 2, 2) as gross_per_mw
  from ranked
 group by 1, 2;

create or replace view daily_extremes as
select settlement_point,
       delivery_date,
       count(*)                             as intervals,
       count(*) filter (where price < 0)    as negative_intervals,
       count(*) filter (where price >= 100) as scarcity_intervals,
       min(price)                           as min_price,
       max(price)                           as max_price,
       round(avg(price), 2)                 as avg_price
  from rt_spp
 where interval_start >= now() - interval '90 days'
 group by 1, 2;

-- Path views: a self-join over 15 points is 105 pairs per interval, so the
-- window matters more here than anywhere else. 90 days still spans a season.
create or replace view path_spread as
select a.settlement_point                                as point_a,
       b.settlement_point                                as point_b,
       count(*)                                          as hours,
       round(avg(b.price - a.price), 2)                  as avg_spread,
       round(stddev_samp(b.price - a.price), 2)          as spread_sd,
       round(100.0 * count(*) filter (where b.price > a.price) / count(*), 1)
                                                         as pct_b_higher,
       round(max(b.price - a.price), 2)                  as max_spread,
       round(min(b.price - a.price), 2)                  as min_spread,
       round(avg(abs(b.price - a.price)), 2)             as avg_abs_spread
  from dam_spp a
  join dam_spp b
    on b.interval_start = a.interval_start
   and a.settlement_point < b.settlement_point
 where a.interval_start >= now() - interval '90 days'
 group by 1, 2;

create or replace view path_spread_dart as
with rt_hourly as (
  select settlement_point,
         date_trunc('hour', interval_start) as hour_start,
         avg(price) as price
    from rt_spp
   where interval_start >= now() - interval '90 days'
   group by 1, 2
)
select da.point_a,
       da.point_b,
       count(*)                                              as hours,
       round(avg(da.dam_spread), 2)                          as avg_dam_spread,
       round(avg(rt.rt_spread), 2)                           as avg_rt_spread,
       round(avg(rt.rt_spread - da.dam_spread), 2)           as avg_miss,
       round(stddev_samp(rt.rt_spread - da.dam_spread), 2)   as miss_sd
  from (
    select a.settlement_point as point_a, b.settlement_point as point_b,
           a.interval_start, b.price - a.price as dam_spread
      from dam_spp a
      join dam_spp b
        on b.interval_start = a.interval_start
       and a.settlement_point < b.settlement_point
     where a.interval_start >= now() - interval '90 days'
  ) da
  join rt_hourly a2 on a2.settlement_point = da.point_a and a2.hour_start = da.interval_start
  join rt_hourly b2 on b2.settlement_point = da.point_b and b2.hour_start = da.interval_start
  join lateral (select b2.price - a2.price as rt_spread) rt on true
 group by 1, 2;

-- Supporting indexes. The (settlement_point, interval_start) primary keys serve
-- point-scoped reads; these serve the time-window scans the views above do.
create index if not exists dam_spp_ts_point_idx on dam_spp (interval_start, settlement_point);
create index if not exists rt_spp_ts_point_idx  on rt_spp  (interval_start, settlement_point);
