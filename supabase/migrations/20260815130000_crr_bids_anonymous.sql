-- crr_bids, rebuilt for the file ERCOT actually publishes.
--
-- The original design keyed bids by (account_holder, ..., bid_price) and
-- grouped its view by account_holder — but the Common_AuctionBidsAndOffers
-- CSV carries no AccountHolder, no AwardedMW, and writes its price as
-- BidPricePerMWH, not the BidPrice/Price the ingest read. Every row was
-- skipped as priceless and the table has been empty since it was created,
-- so this rebuild loses nothing.
--
-- The BUY side mirrors crr_offers (the same file's SELL rows): anonymous
-- curve segments with no natural key — one path can carry many segments at
-- identical prices from different (anonymous) bidders — so row_num, the
-- position among BUY rows in file order, is the identity. Stable for a
-- published auction file, so re-ingest is idempotent.

drop view if exists crr_bid_aggression;
drop table if exists crr_bids;

create table crr_bids (
  auction_name text not null references crr_auctions(auction_name) on delete cascade,
  row_num      integer not null,       -- position among BUY rows in the published file
  source       text not null,
  sink         text not null,
  time_of_use  text not null,
  hedge_type   text not null,          -- OBL | OPT
  start_date   date not null,
  end_date     date not null,
  mw           numeric(12,2),
  bid_price    numeric(14,6),          -- BidPricePerMWH: most the bidder would pay
  shadow_price numeric(14,6),          -- the path's clearing shadow price
  -- A BUY clears when its price reaches the market's. Derived, and
  -- approximate at the margin (a marginal segment may partially clear).
  cleared      boolean generated always as
                 (case when bid_price is null or shadow_price is null then null
                       else bid_price >= shadow_price end) stored,
  ingested_at  timestamptz not null default now(),
  primary key (auction_name, row_num)
);

create index crr_bids_path_idx on crr_bids (source, sink);
create index crr_bids_tou_idx  on crr_bids (time_of_use);

alter table crr_bids enable row level security;
drop policy if exists crr_bids_read on crr_bids;
create policy crr_bids_read on crr_bids for select using (true);
grant select on crr_bids to anon, authenticated;

-- What crr_bid_aggression wanted to measure — which firms must fill
-- regardless of price — is unanswerable without account_holder. What the
-- anonymous rows do support is demand pressure per path: how much MW chased
-- it, and how much of that was priced at or above where the path cleared.
create or replace view crr_bid_pressure as
select auction_name, source, sink, time_of_use, hedge_type,
       count(*)                                        as bids,
       round(sum(mw)::numeric, 1)                      as mw_bid,
       round(coalesce(sum(mw) filter (where cleared), 0)::numeric, 1)
                                                       as mw_at_or_above_clear,
       round((100.0 * coalesce(sum(mw) filter (where cleared), 0)
              / nullif(sum(mw), 0))::numeric, 1)       as pct_at_or_above_clear,
       round(max(bid_price)::numeric, 4)               as max_bid,
       round(min(shadow_price)::numeric, 4)            as shadow_price
  from crr_bids
 group by 1, 2, 3, 4, 5;

grant select on crr_bid_pressure to anon, authenticated;
