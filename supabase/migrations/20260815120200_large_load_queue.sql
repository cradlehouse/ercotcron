-- Large Load interconnection queue: AGGREGATES ONLY, because that is all
-- ERCOT publishes.
--
-- Per-project large-load queue data is confidential. NPRR1267 (approved by
-- the PUCT 2025-07-31) mandates a monthly public Large Load Interconnection
-- Status Report, but as of 2026-08-15 it has not been implemented: it appears
-- in no EMIL data product, no MIS report type, and no api.ercot.com product.
-- The public record is the monthly "Large Load Interconnection Status Update"
-- deck presented to TAC (PDF; most figures live in chart images), from which
-- only the narrative headline numbers are machine-extractable.
--
-- So this table is a long-format aggregate store: one row per report per
-- metric. When the NPRR1267 report ships with real per-project rows, add a
-- second table rather than torturing this one.

create table if not exists large_load_queue (
  report_month  date not null,          -- month of the status update deck
  metric        text not null,          -- e.g. approved_to_energize_mw, simultaneous_peak_mw
  category      text not null default '',  -- optional dimension (zone, size band) when parseable
  mw            numeric,
  projects      integer,
  source_url    text not null,          -- the deck the number came from
  note          text,                   -- the sentence the number was pulled from
  ingested_at   timestamptz not null default now(),
  primary key (report_month, metric, category)
);

alter table large_load_queue enable row level security;
drop policy if exists large_load_queue_read on large_load_queue;
create policy large_load_queue_read on large_load_queue
  for select using (true);
grant select on large_load_queue to anon, authenticated;
