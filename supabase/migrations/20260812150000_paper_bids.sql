-- Paper-trading rail: Steve's dummy bids, stored immutably before the auction
-- clears, scored later against clearing prices and then realized payoffs.
-- Same append-only discipline as mark_runs (methodology §8): a paper bid can
-- never be edited after the fact, so the look-back is honest.

create table if not exists paper_bids (
  batch_id     text not null,              -- e.g. '2026-09-monthly-steve-1'
  submitted_at timestamptz not null default now(),
  auction_name text not null,              -- e.g. 'SEP2026Monthly'
  source       text not null,
  sink         text not null,
  time_of_use  text not null,
  hedge_type   text not null,
  mw           numeric not null,
  bid_price    numeric not null,           -- the limit from the bid sheet
  -- scored after the auction publishes:
  clearing_price numeric,
  cleared        boolean,
  -- scored after the delivery month settles:
  realized_value numeric,                  -- $/MW over the TOU block
  pnl            numeric,
  scored_at      timestamptz,
  primary key (batch_id, source, sink, time_of_use, hedge_type, bid_price, mw)
);

-- Append-only for the bid columns; scoring may only fill the result columns.
create or replace function paper_bids_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'paper_bids is append-only';
  end if;
  if new.batch_id <> old.batch_id or new.submitted_at <> old.submitted_at
     or new.auction_name <> old.auction_name or new.source <> old.source
     or new.sink <> old.sink or new.time_of_use <> old.time_of_use
     or new.hedge_type <> old.hedge_type or new.mw <> old.mw
     or new.bid_price <> old.bid_price then
    raise exception 'paper_bids: bid fields are immutable; only scoring columns may be updated';
  end if;
  return new;
end $$;

drop trigger if exists paper_bids_guard on paper_bids;
create trigger paper_bids_guard
  before update or delete on paper_bids
  for each row execute function paper_bids_guard();

alter table paper_bids enable row level security;
