-- crr_point_prices was keyed on (auction, settlement point, time of use) without
-- the calendar month. Long-term auctions price six months per file, so each
-- node kept only the last month written. The key now includes the month; the
-- long-term auctions are re-ingested afterwards (scripts/reingest_lt_point_prices.py).
alter table crr_point_prices alter column calendar_period set not null;
alter table crr_point_prices drop constraint crr_point_prices_pkey;
alter table crr_point_prices
  add constraint crr_point_prices_pkey
  primary key (auction_name, settlement_point, time_of_use, calendar_period);
