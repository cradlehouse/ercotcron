-- CRR offers: the sell side of the auction file we already parse for bids.
--
-- An offer is an existing holder trying to get out. Where bids reveal what
-- firms will pay for congestion exposure, offers reveal which paths current
-- holders no longer want and the least they will accept to shed them — the
-- capitulation record. The rows live in the same AuctionBidsAndOffers CSV as
-- the bids, distinguished by BidType = SELL.
--
-- NOTE the file's actual columns (2026 vintage): Source, Sink, BidType,
-- StartDate, EndDate, HedgeType, TimeOfUse, MW, BidPricePerMWH,
-- ShadowPricePerMWH. There is NO AccountHolder and NO AwardedMW — offers are
-- anonymous curve segments. (This same schema is why crr_bids has been
-- loading zero rows: ercot/crr.py reads a "BidPrice" column that does not
-- exist in these files.)
--
-- Identity: the file gives no natural key — one path can carry many segments
-- at identical prices from different (anonymous) holders. row_num is the
-- segment's position among SELL rows in file order, which is stable for a
-- published auction file, so re-ingest is idempotent.

create table if not exists crr_offers (
  auction_name text not null references crr_auctions(auction_name) on delete cascade,
  row_num      integer not null,       -- position among SELL rows in the published file
  source       text not null,
  sink         text not null,
  time_of_use  text not null,
  hedge_type   text not null,          -- OBL | OPT
  start_date   date not null,
  end_date     date not null,
  mw           numeric(12,2),
  min_price    numeric(14,6),          -- BidPricePerMWH: least the holder would accept
  shadow_price numeric(14,6),          -- the path's clearing shadow price
  -- A SELL clears when the market price reaches the seller's floor. Derived,
  -- and approximate at the margin (a marginal segment may partially clear).
  cleared      boolean generated always as
                 (case when min_price is null or shadow_price is null then null
                       else shadow_price >= min_price end) stored,
  ingested_at  timestamptz not null default now(),
  primary key (auction_name, row_num)
);

create index if not exists crr_offers_path_idx on crr_offers (source, sink);
create index if not exists crr_offers_tou_idx  on crr_offers (time_of_use);

alter table crr_offers enable row level security;
drop policy if exists crr_offers_read on crr_offers;
create policy crr_offers_read on crr_offers for select using (true);
grant select on crr_offers to anon, authenticated;
