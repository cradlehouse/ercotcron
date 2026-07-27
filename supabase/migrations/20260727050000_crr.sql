-- CRR auction results: what a congestion right cost to buy.
--
-- These come from ERCOT's MIS (www.ercot.com/misapp/GetReports.do), not the
-- public reports API — a different host, no authentication, zipped CSV rather
-- than JSON. They are the half the price feeds cannot supply: dam_spp says what
-- a path paid, this says what it cost, and only the two together are P&L.

create table if not exists crr_auctions (
  auction_name  text primary key,          -- '2026.AUG.Monthly.Auction'
  report_type   text        not null,      -- monthly | long_term
  doc_lookup_id text,
  file_name     text,
  awards        integer     not null default 0,
  ingested_at   timestamptz not null default now()
);

create table if not exists crr_awards (
  auction_name   text not null references crr_auctions(auction_name) on delete cascade,
  crr_id         text not null,
  time_of_use    text not null,            -- PeakWD | PeakWE | Off-peak
  account_holder text,
  -- OBL pays the congestion difference whatever its sign; OPT pays only when
  -- positive. The distinction decides the payoff formula, so it is not cosmetic.
  hedge_type     text not null,            -- OPT | OBL
  bid_type       text not null,            -- BUY | SELL
  crr_type       text,
  source         text not null,
  sink           text not null,
  start_date     date not null,
  end_date       date not null,
  mw             numeric(12,2),
  clearing_price numeric(14,6),            -- ShadowPricePerMWH, $/MWh
  ingested_at    timestamptz not null default now(),
  primary key (auction_name, crr_id, time_of_use)
);

create index if not exists crr_awards_path_idx   on crr_awards (source, sink);
create index if not exists crr_awards_period_idx on crr_awards (start_date, end_date);
create index if not exists crr_awards_holder_idx on crr_awards (account_holder);

-- Nodal shadow price per settlement point per time-of-use block, from the same
-- auction. Useful where a path's source or sink is a node we do not price.
create table if not exists crr_point_prices (
  auction_name     text not null references crr_auctions(auction_name) on delete cascade,
  settlement_point text not null,
  time_of_use      text not null,
  calendar_period  text,
  shadow_price     numeric(14,6),
  primary key (auction_name, settlement_point, time_of_use)
);

-- --------------------------------------------------------------- time of use --

-- ERCOT's blocks: peak is hours ending 7–22; weekday peak is Mon–Fri, weekend
-- peak is Sat/Sun *and NERC holidays*; everything else is off-peak.
--
-- Holidays are NOT handled: a NERC holiday falling on a weekday is classified
-- PeakWD here where ERCOT would call it PeakWE. That is roughly six days a
-- year, so any single award's hour count can be off by a few percent. Fixing it
-- needs a holiday calendar; until then treat P&L on those days as approximate
-- rather than assuming the blocks align exactly.
create or replace function crr_time_of_use(p_date date, p_hour_ending int)
returns text language sql immutable as $$
  select case
    when p_hour_ending < 7 or p_hour_ending > 22 then 'Off-peak'
    when extract(isodow from p_date) <= 5        then 'PeakWD'
    else 'PeakWE'
  end;
$$;

-- ------------------------------------------------------------------- P&L --

-- Cost against realised congestion, per MW, for awards whose source and sink
-- are both priced in dam_spp. Most auction paths are nodes this platform does
-- not track, so coverage is partial by construction — hours_matched shows how
-- much of the award's term was actually priced, and a low count means the
-- number below it is not a verdict.
create or replace view crr_pnl as
with priced as (
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
  from crr_awards a
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

grant select on crr_auctions, crr_awards, crr_point_prices, crr_pnl
   to anon, authenticated;
grant execute on function crr_time_of_use(date, int) to anon, authenticated;
