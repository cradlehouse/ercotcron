-- Trade-lens views: the three ways this data is actually traded.

-- ------------------------------------------------------------ DART spread --
-- Day-ahead vs real-time, the fundamental ERCOT trade. A positive spread means
-- real-time settled above the day-ahead price (buying DA won); negative means
-- DA was the overpay. RT is a 15-minute series, so it is averaged up to the
-- DAM hour (four equal-weight intervals per hour).

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
     group by 1, 2
  ) r
    on r.settlement_point = d.settlement_point
   and r.hour_start       = d.interval_start;

-- ------------------------------------------------- 2-hour battery arbitrage --
-- The standard storage benchmark: charge the two cheapest hours of the day,
-- discharge the two most expensive. gross_per_mw is $/MW-day before round-trip
-- efficiency (a real battery keeps roughly 85% of it). delivery_date is the
-- ERCOT operating day, so no timezone arithmetic here.

create or replace view daily_battery_arb as
with hourly as (
  select settlement_point,
         delivery_date,
         date_trunc('hour', interval_start) as hour_start,
         avg(price) as price
    from rt_spp
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

-- --------------------------------------------------------- daily extremes --
-- Negative intervals are the flexible-load signal (curtail-or-get-paid hours);
-- scarcity intervals ($100+) are what batteries and peakers live on.

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
 group by 1, 2;

-- Views run as their owner; grant the read roles explicit select, matching
-- 20260726120300_rls.sql.
grant select on dart_spread, daily_battery_arb, daily_extremes
   to anon, authenticated;
