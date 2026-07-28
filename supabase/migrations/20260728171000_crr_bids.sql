-- Losing bids: the behavioural record the awards cannot supply.
--
-- An award says what cleared. A bid says what a firm was willing to pay and did
-- not get, which is the only way to tell a price-insensitive hedger from an
-- opportunist who happened to win. Every question this session asked about who
-- is aggressive and who is mandated needed this file, and it was being
-- discarded on the grounds that it "answers nothing the awards do not".

create table if not exists crr_bids (
  auction_name   text not null references crr_auctions(auction_name) on delete cascade,
  account_holder text not null default '',
  hedge_type     text not null,
  bid_type       text not null,
  source         text not null,
  sink           text not null,
  start_date     date not null,
  end_date       date not null,
  time_of_use    text not null,
  mw             numeric(12,2),
  bid_price      numeric(14,6),
  awarded_mw     numeric(12,2),
  ingested_at    timestamptz not null default now(),
  -- A firm may bid the same path at several prices; price is part of identity.
  primary key (auction_name, account_holder, source, sink, time_of_use,
               hedge_type, bid_type, bid_price)
);

create index if not exists crr_bids_holder_idx on crr_bids (account_holder);
create index if not exists crr_bids_path_idx   on crr_bids (source, sink);

-- Bid-to-clear distance per firm: how far above or below the clearing price
-- each was willing to go. Persistent overbidding is the signature of a hedger
-- who must fill regardless of price.
create or replace view crr_bid_aggression as
select b.auction_name,
       b.account_holder,
       b.hedge_type,
       count(*)                                             as bids,
       round(sum(b.mw)::numeric, 1)                         as mw_bid,
       round(sum(coalesce(b.awarded_mw, 0))::numeric, 1)    as mw_won,
       round((100.0 * sum(coalesce(b.awarded_mw, 0))
              / nullif(sum(b.mw), 0))::numeric, 1)          as fill_rate,
       round(avg(b.bid_price - p.vw_price)::numeric, 4)     as avg_over_clear
  from crr_bids b
  join crr_path_price p
    on p.auction_name = b.auction_name
   and p.source       = b.source
   and p.sink         = b.sink
   and p.time_of_use  = b.time_of_use
   and p.hedge_type   = b.hedge_type
 where b.bid_type = 'BUY'
 group by 1, 2, 3
having count(*) >= 5;

grant select on crr_bids, crr_bid_aggression to anon, authenticated;
