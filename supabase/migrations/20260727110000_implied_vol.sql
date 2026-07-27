-- What the auction charges for uncertainty.
--
-- Two instruments trade on the same path, month and time-of-use block. An
-- obligation pays the congestion difference whichever way it goes; an option
-- pays only when it is positive. The option therefore costs more, and that
-- premium is the market quoting the value of not being on the wrong side —
-- which is an implied volatility.
--
-- Unlike the P&L views this needs no price history at all. It is computed
-- entirely from the auction file, so it covers every settlement point ERCOT
-- auctions rather than the handful this platform prices. That is the point:
-- the liquid hub paths are well modelled and fairly priced, and anything
-- mispriced is far more likely to sit in the nodal tail nobody watches.

-- Volume-weighted clearing price per path, block and instrument. Weighting by
-- MW matters: a 0.5 MW award at a silly price and a 200 MW award at a real one
-- are not equal evidence of what the market thinks.
create or replace view crr_path_price as
select auction_name,
       source,
       sink,
       time_of_use,
       hedge_type,
       count(*)                                                       as awards,
       round(sum(mw)::numeric, 1)                                     as total_mw,
       round((sum(mw * clearing_price) / nullif(sum(mw), 0))::numeric, 5)
                                                                      as vw_price,
       round(min(clearing_price)::numeric, 5)                         as min_price,
       round(max(clearing_price)::numeric, 5)                         as max_price,
       -- ERCOT clears a uniform price per path, block and instrument, so this
       -- is 1 for 99.9% of groups. Where it is not, the volume-weighted mean
       -- averages prices that belong to different products and the result is
       -- meaningless — it manufactured an apparent option-cheaper-than-
       -- obligation arbitrage on the largest path in the August auction.
       -- Surfaced rather than smoothed, and excluded downstream.
       count(distinct clearing_price)                                 as price_count
  from crr_awards
 where bid_type = 'BUY'          -- offers to sell are a different question
   and mw > 0
 group by 1, 2, 3, 4, 5;

-- The premium itself. Positive means the option costs more than the
-- obligation, which is the normal state; the size is what the market is
-- charging for uncertainty on that path.
create or replace view crr_implied_vol as
select o.auction_name,
       o.source,
       o.sink,
       o.time_of_use,
       o.vw_price                                        as option_price,
       b.vw_price                                        as obligation_price,
       round((o.vw_price - b.vw_price)::numeric, 5)      as premium,
       -- Scale-free, so a cheap path and an expensive one are comparable. Guard
       -- the denominator: obligations near zero make the ratio meaningless
       -- rather than large.
       case when abs(b.vw_price) >= 0.05
            then round(((o.vw_price - b.vw_price) / abs(b.vw_price))::numeric, 3)
       end                                               as premium_ratio,
       o.total_mw                                        as option_mw,
       b.total_mw                                        as obligation_mw,
       o.awards + b.awards                               as awards
  from crr_path_price o
  join crr_path_price b
    on b.auction_name = o.auction_name
   and b.source       = o.source
   and b.sink         = o.sink
   and b.time_of_use  = o.time_of_use
   and b.hedge_type   = 'OBL'
 where o.hedge_type = 'OPT'
   -- Both sides must have cleared at a single price for the premium to mean
   -- anything. An option cannot rationally cost less than an obligation on the
   -- same path: it pays max(0, congestion) where the obligation also pays the
   -- negative side. A negative premium here is a data artifact, not an edge.
   and o.price_count = 1
   and b.price_count = 1;

-- Averaged across auctions, so a single odd month does not define a path.
-- Paths where the premium is persistently thin are where the market is treating
-- congestion as predictable — the interesting list to cross against weather
-- uncertainty, because that is where a surprise is least priced in.
create or replace view crr_implied_vol_summary as
select source,
       sink,
       time_of_use,
       count(*)                                              as auctions,
       round(avg(premium)::numeric, 5)                       as avg_premium,
       round(stddev_samp(premium)::numeric, 5)               as premium_sd,
       round(avg(premium_ratio)::numeric, 3)                 as avg_premium_ratio,
       round(avg(option_price)::numeric, 5)                  as avg_option_price,
       round(avg(obligation_price)::numeric, 5)              as avg_obligation_price,
       round(sum(option_mw + obligation_mw)::numeric, 0)     as total_mw
  from crr_implied_vol
 group by 1, 2, 3
having count(*) >= 3;

grant select on crr_path_price, crr_implied_vol, crr_implied_vol_summary
   to anon, authenticated;
