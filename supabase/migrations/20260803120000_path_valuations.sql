-- Pre-auction path valuations: what a path has been worth, versus what was bid.
--
-- Deliberately stores the distribution, not just the mean. A $6 average with a
-- $200 left tail is a different trade from a $6 average with a $2 one, and the
-- mean alone has misled this project repeatedly.
--
-- `book` names whose bid list this row was scored against, so several books can
-- coexist. Rows are replaced per (book, path, tou, hedge) on each run.
create table if not exists path_valuations (
  book            text not null,
  source          text not null,
  sink            text not null,
  time_of_use     text not null,
  hedge_type      text not null,
  mw              numeric,
  bids            int,
  bid_price       numeric,          -- MW-weighted average bid
  value_mean      numeric,          -- realised congestion, trailing window
  value_median    numeric,
  value_p05       numeric,          -- the tail being underwritten
  value_p95       numeric,
  pct_hours_pos   numeric,
  hours           int,
  edge            numeric,          -- value_mean - bid_price
  drivers         text,             -- constraints that move the sink
  warnings        text,             -- stale/re-rated driver flags
  window_start    date,
  window_end      date,
  computed_at     timestamptz not null default now(),
  primary key (book, source, sink, time_of_use, hedge_type)
);

create index if not exists path_valuations_edge_idx on path_valuations (book, edge desc);

alter table path_valuations enable row level security;
drop policy if exists path_valuations_read on path_valuations;
create policy path_valuations_read on path_valuations for select using (true);
grant select on path_valuations to anon, authenticated;
