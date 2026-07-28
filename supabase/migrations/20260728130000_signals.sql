-- Opportunity surfacing: time series, persistence, tails, and basis pairs.
--
-- A Sankey needs a conserved quantity flowing between stages. Prices are not
-- conserved — megawatt-hours are — so flow diagrams answer "where did the power
-- go" and cannot answer "where is value mispriced". These four views are the
-- latter question, and all of them keep a time axis, which is the thing a
-- snapshot diagram structurally cannot have.

-- ------------------------------------------------------- 1. spread z-score --

-- Day-ahead minus real-time per settlement point per hour, scored against its
-- own trailing 7 days.
--
-- The window is `168 preceding and 1 preceding` — it deliberately excludes the
-- current hour. Including it would let each observation contribute to the mean
-- it is being scored against, which flatters every extreme value and is the
-- most common way a "signal" turns out to be lookahead.
create or replace view spread_zscore as
with hourly as (
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
   where d.interval_start >= now() - interval '120 days'
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
  from scored;

-- ------------------------------------------------- 2. node x hour heatmap --

-- Which point/hour cells are persistently mispriced rather than occasionally
-- extreme. t_stat is the column to sort on: a large mean spread with larger
-- variance is noise, and ranking by mean alone surfaces the loudest cells
-- instead of the most repeatable ones.
create or replace view node_hour_spread as
with hourly as (
  select d.settlement_point,
         d.hour_ending,
         d.price - avg(r.price) as spread
    from dam_spp d
    join rt_spp r
      on r.settlement_point = d.settlement_point
     and r.interval_start >= d.interval_start
     and r.interval_start <  d.interval_start + interval '1 hour'
   where d.interval_start >= now() - interval '180 days'
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
having count(*) >= 30;

-- ------------------------------------------------------ 3. duration curve --

-- The distribution, not the average. A strategy that collects a small premium
-- most hours and pays it all back in a handful is invisible in a mean and
-- obvious here — p99 against p50 is the sizing question for anything that sells
-- optionality.
create or replace view spread_duration as
with hourly as (
  select d.settlement_point,
         d.price - avg(r.price) as spread
    from dam_spp d
    join rt_spp r
      on r.settlement_point = d.settlement_point
     and r.interval_start >= d.interval_start
     and r.interval_start <  d.interval_start + interval '1 hour'
   where d.interval_start >= now() - interval '180 days'
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
       -- How lopsided the tails are. Well above 1 means the downside tail is
       -- fatter than the upside, which is the shape that ruins premium sellers.
       round((abs(percentile_cont(0.01) within group (order by spread))
              / nullif(percentile_cont(0.99) within group (order by spread), 0))::numeric, 2)
                                                                         as tail_ratio
  from hourly
 group by 1
having count(*) >= 100;

-- --------------------------------------------------- 4. basis correlation --

-- Pairwise correlation of hourly day-ahead prices. Pairs that normally move
-- together and then stop are basis trades; the correlation is what says
-- "normally".
--
-- Restricted to the tracked hubs and zones: this is O(n^2) in points, and at
-- ~987 nodes it would be roughly 486,000 pairs recomputed per request.
create or replace view basis_correlation as
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
  join settlement_points sa on sa.name = a.settlement_point
  join settlement_points sb on sb.name = b.settlement_point
 where a.interval_start >= now() - interval '180 days'
   and a.settlement_point like any (array['HB\_%', 'LZ\_%'])
   and b.settlement_point like any (array['HB\_%', 'LZ\_%'])
 group by 1, 2
having count(*) >= 100;

grant select on spread_zscore, node_hour_spread, spread_duration, basis_correlation
   to anon, authenticated;
