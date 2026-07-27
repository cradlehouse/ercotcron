-- Path spreads: the payoff side of a congestion revenue right.
--
-- An ERCOT PTP Obligation pays the congestion difference between a source and a
-- sink. The day-ahead price difference between two settlement points is that
-- difference (congestion plus losses), so two years of dam_spp already contains
-- the payoff history for every path between tracked points — 105 pairs from 15
-- points, with no additional ingestion.
--
-- What is NOT here is the auction clearing price: what a CRR cost to buy. That
-- lives in ERCOT's CRR/MIS system, not the public reports API, so these views
-- rank which paths *paid*, not which were profitable. Do not read avg_spread as
-- profit.

-- Pair ordering is a < b, so each path appears once. Direction is a sign, not a
-- second row: a source→sink obligation and its reverse are the same number
-- negated, and storing both would double the table to say the same thing.
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
 where a.interval_start >= now() - interval '365 days'
 group by 1, 2;

-- Day-ahead against real-time on the same path. A CRR is settled day-ahead, so
-- a path whose day-ahead spread persistently misses the realised one is where
-- the day-ahead market is mispricing congestion — which is the interesting
-- question, and the one the two markets together can answer.
create or replace view path_spread_dart as
with rt_hourly as (
  select settlement_point,
         date_trunc('hour', interval_start) as hour_start,
         avg(price) as price
    from rt_spp
   where interval_start >= now() - interval '365 days'
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
     where a.interval_start >= now() - interval '365 days'
  ) da
  join (
    select a.settlement_point as point_a, b.settlement_point as point_b,
           a.hour_start, b.price - a.price as rt_spread
      from rt_hourly a
      join rt_hourly b
        on b.hour_start = a.hour_start
       and a.settlement_point < b.settlement_point
  ) rt
    on rt.point_a = da.point_a and rt.point_b = da.point_b
   and rt.hour_start = da.interval_start
 group by 1, 2;

grant select on path_spread, path_spread_dart to anon, authenticated;
