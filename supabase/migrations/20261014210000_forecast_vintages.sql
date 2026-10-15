-- ERCOT forecasts as they stood at decision time, from ERCOT's own archive.
--
-- ERCOT re-issues its 7-day load (NP3-561-CD), wind (NP4-742-CD) and solar
-- (NP4-745-CD) forecasts hourly and keeps every edition. For each operating
-- day we keep the edition posted at 09:30 Central (the last before the 10:00
-- DAM bid deadline), so a replay can use exactly what was known when the day-
-- ahead market cleared - the information-set rule in the grid replay plan
-- addendum. One row per (product, edition, delivery day, series); hours as an
-- array ordered by (hour ending, DST flag). Columns that are actuals in the
-- source file (e.g. GEN_*) are kept and labelled by their source name: they
-- are only known for hours already past at posting time.

create table if not exists ercot_forecast_vintages (
  product        text        not null,   -- NP3-561-CD | NP4-742-CD | NP4-745-CD
  posted_at      timestamp   not null,   -- ERCOT postDatetime (Central, as published)
  delivery_date  date        not null,
  series         text        not null,   -- source column, e.g. Coast, STWPF_PANHANDLE
  vals           real[]      not null,
  primary key (product, posted_at, delivery_date, series)
);

alter table ercot_forecast_vintages enable row level security;
revoke all on ercot_forecast_vintages from anon, authenticated;
