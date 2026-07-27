-- The three "why" questions, answered in SQL.
--
-- Postgres does the statistics natively (regr_slope, regr_r2, corr,
-- percentile_cont), so none of this needs a Python pipeline or a second copy of
-- the data. Every view below is honest about its own sample size, because the
-- failure mode here is not a wrong number — it is a confident number computed
-- from six observations.

-- ------------------------------------------------------- 1. the supply stack --

-- Price against net load. ERCOT's stack is flat for most of its range and then
-- vertical: the interesting output is not the average but where p95 detaches
-- from the median, because that is where scarcity begins.
create or replace view price_stack as
select width_bucket(n.net_load_mw, 20000, 85000, 26)        as bucket,
       round(min(n.net_load_mw))                            as net_load_from,
       round(max(n.net_load_mw))                            as net_load_to,
       count(*)                                             as hours,
       round(percentile_cont(0.5) within group (order by d.price)::numeric, 2)  as median_price,
       round(percentile_cont(0.95) within group (order by d.price)::numeric, 2) as p95_price,
       round(avg(d.price), 2)                               as avg_price,
       round(100.0 * count(*) filter (where d.price >= 100) / count(*), 1)      as pct_scarcity,
       round(100.0 * count(*) filter (where d.price < 0) / count(*), 1)         as pct_negative
  from net_load n
  join dam_spp d
    on d.interval_start = n.interval_start
   and d.settlement_point = 'HB_HUBAVG'
 where n.net_load_mw is not null
 group by 1
having count(*) >= 10;

-- --------------------------------------------- 2. wind sensitivity by hour --

-- How much a megawatt of wind moves the price, per hour of the day. regr_slope
-- is $/MWh per MW of wind, so it is normally negative — more wind, cheaper
-- power. r2 says how much of the price that explains; a steep slope with a
-- trivial r2 is a coincidence, so both are reported and neither alone.
create or replace view wind_sensitivity as
select n.hour_ending,
       count(*)                                                   as hours,
       round(regr_slope(d.price, n.wind_mw)::numeric, 5)          as price_per_mw_wind,
       round(regr_r2(d.price, n.wind_mw)::numeric, 3)             as r2,
       round(corr(d.price, n.wind_mw)::numeric, 3)                as correlation,
       round(avg(n.wind_mw))                                      as avg_wind_mw,
       round(avg(d.price), 2)                                     as avg_price
  from net_load n
  join dam_spp d
    on d.interval_start = n.interval_start
   and d.settlement_point = 'HB_HUBAVG'
 where n.wind_mw is not null
 group by 1
having count(*) >= 30;

-- Forecast error against price. wind_miss_mw is signed — positive means more
-- wind blew than expected — so a negative slope is the tradeable direction:
-- wind under-delivers, price rises.
create or replace view wind_miss_impact as
select n.hour_ending,
       count(*)                                                        as hours,
       round(regr_slope(d.price, n.wind_miss_mw)::numeric, 5)          as price_per_mw_miss,
       round(regr_r2(d.price, n.wind_miss_mw)::numeric, 3)             as r2,
       round(avg(abs(n.wind_miss_mw)))                                 as avg_abs_miss_mw,
       round(stddev_samp(n.wind_miss_mw))                              as miss_sd_mw
  from net_load n
  join dam_spp d
    on d.interval_start = n.interval_start
   and d.settlement_point = 'HB_HUBAVG'
 where n.wind_miss_mw is not null
 group by 1
having count(*) >= 30;

-- ------------------------------------------------------ 3. the CRR edge --

-- Per path and time-of-use block, what the auction charged against what the
-- path actually paid, across every auction loaded.
--
-- `t_stat` is the column that matters and the only one worth acting on: mean
-- edge over its own standard error. A $2 edge with $8 of noise across twelve
-- auctions is nothing; $2 with $0.80 is a signal. Ranking by avg_edge alone
-- would put the loudest paths on top rather than the most reliable ones, which
-- is exactly how a backtest gets talked into a strategy.
create or replace view crr_edge as
with per_auction as (
  select source, sink, time_of_use, hedge_type, auction_name,
         sum(mw * clearing_price * hours_matched)          as cost,
         sum(mw * payoff_per_mw)                           as payoff,
         sum(mw * hours_matched)                           as mwh,
         avg(clearing_price)                               as clearing_price,
         avg(payoff_per_mw / nullif(hours_matched, 0))     as payoff_per_mwh
    from crr_pnl
   where hours_matched > 0
   group by 1, 2, 3, 4, 5
)
select source,
       sink,
       time_of_use,
       hedge_type,
       count(*)                                                     as auctions,
       round(avg(clearing_price)::numeric, 4)                       as avg_cost_per_mwh,
       round(avg(payoff_per_mwh)::numeric, 4)                       as avg_payoff_per_mwh,
       round(avg(payoff_per_mwh - clearing_price)::numeric, 4)      as avg_edge_per_mwh,
       round(stddev_samp(payoff_per_mwh - clearing_price)::numeric, 4) as edge_sd,
       round((avg(payoff_per_mwh - clearing_price)
              / nullif(stddev_samp(payoff_per_mwh - clearing_price), 0)
              * sqrt(count(*)))::numeric, 2)                        as t_stat,
       round(sum(payoff - cost)::numeric, 0)                        as net_total,
       round(100.0 * count(*) filter (where payoff > cost) / count(*), 0) as pct_profitable
  from per_auction
 group by 1, 2, 3, 4
having count(*) >= 4;

grant select on price_stack, wind_sensitivity, wind_miss_impact, crr_edge
   to anon, authenticated;
