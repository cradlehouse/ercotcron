-- Make the CRR P&L computable.
--
-- crr_pnl joined 1,019,106 awards against 263,160 prices with a BETWEEN on the
-- delivery date, twice — once for the source and once for the sink. That is an
-- analytical aggregate over millions of row pairs, and it was written as a
-- plain view, so every page load recomputed it and hit the statement timeout.
--
-- Two changes. First, only awards whose source *and* sink are both priced here
-- can contribute anything, and that is about 2% of them — filtering before the
-- join rather than after removes 98% of the work. Second, the result is
-- refreshed on a schedule rather than per request: auction results change when
-- a new auction clears, roughly monthly, so recomputing on page view was buying
-- freshness that does not exist.

drop view if exists crr_edge;
drop view if exists crr_pnl;

create materialized view if not exists crr_pnl as
with priced_points as (
  select distinct settlement_point from dam_spp
), eligible as (
  select a.*
    from crr_awards a
   where exists (select 1 from priced_points p where p.settlement_point = a.source)
     and exists (select 1 from priced_points p where p.settlement_point = a.sink)
), priced as (
  select settlement_point, delivery_date, hour_ending, price,
         crr_time_of_use(delivery_date, hour_ending) as tou
    from dam_spp
)
select a.auction_name,
       a.crr_id,
       a.account_holder,
       a.hedge_type,
       a.bid_type,
       a.source,
       a.sink,
       a.time_of_use,
       a.mw,
       a.clearing_price,
       count(*)                                              as hours_matched,
       round(sum(a.clearing_price), 2)                       as cost_per_mw,
       round(sum(
         case when a.hedge_type = 'OPT'
              then greatest(snk.price - src.price, 0)
              else snk.price - src.price
         end), 2)                                            as payoff_per_mw,
       round(sum(
         case when a.hedge_type = 'OPT'
              then greatest(snk.price - src.price, 0)
              else snk.price - src.price
         end - a.clearing_price), 2)                         as net_per_mw,
       round(a.mw * sum(
         case when a.hedge_type = 'OPT'
              then greatest(snk.price - src.price, 0)
              else snk.price - src.price
         end - a.clearing_price), 2)                         as net_total
  from eligible a
  join priced src
    on src.settlement_point = a.source
   and src.delivery_date between a.start_date and a.end_date
   and src.tou = a.time_of_use
  join priced snk
    on snk.settlement_point = a.sink
   and snk.delivery_date = src.delivery_date
   and snk.hour_ending    = src.hour_ending
 group by a.auction_name, a.crr_id, a.account_holder, a.hedge_type, a.bid_type,
          a.source, a.sink, a.time_of_use, a.mw, a.clearing_price;

-- Unique index is required for REFRESH ... CONCURRENTLY, which is what keeps
-- the page readable while the refresh runs.
create unique index if not exists crr_pnl_key_idx
  on crr_pnl (auction_name, crr_id, time_of_use);
create index if not exists crr_pnl_path_idx on crr_pnl (source, sink);

-- Supports the BETWEEN scan the materialised view does per award.
create index if not exists dam_spp_point_date_idx on dam_spp (settlement_point, delivery_date);

create or replace view crr_edge as
with per_auction as (
  select source, sink, time_of_use, hedge_type, auction_name,
         sum(mw * clearing_price * hours_matched)          as cost,
         sum(mw * payoff_per_mw)                           as payoff,
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

grant select on crr_pnl, crr_edge to anon, authenticated;
