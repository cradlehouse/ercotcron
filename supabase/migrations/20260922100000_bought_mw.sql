-- Tim's standard, made permanent: a fill is only CLAIMED when real buyers
-- took the path. bought_mw records the auction's actual buy-side volume per
-- row (a scoring column — the identity guard already permits it); displays
-- lead with buyer-backed fills and name the sell-only rows as unclaimed.
alter table sheet_snapshots add column if not exists bought_mw numeric;

update sheet_snapshots s
   set bought_mw = coalesce((
     select sum(a.mw) from crr_awards a
      where a.auction_name = split_part(s.sheet, '-', 1)
        and a.bid_type = 'BUY'
        and a.source = s.source and a.sink = s.sink
        and a.time_of_use = s.time_of_use and a.hedge_type = s.hedge_type), 0)
 where s.clearing is not null;
