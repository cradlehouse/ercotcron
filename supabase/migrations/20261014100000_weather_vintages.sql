-- Weather forecast vintages: every forecast as it was seen, never overwritten.
--
-- weather_forecast keeps one value per (hour, region, model) and the hourly
-- job replaces it, so a forecast stored days ahead is later swapped for a
-- near-term one. That table cannot say what was known at an auction cutoff
-- (docs/WEATHER_PREDICTIVE_REVIEW_2026-10-13.md, finding 1). It stays as-is
-- for its current consumers; this table is the archive alongside it.
--
-- One row = one site's forecast series for one model, as returned by one
-- fetch: values from valid_start onward, one per step_seconds. Site level, not
-- the region mean, so capacity weighting and per-site power curves can be
-- applied later (finding 4). Arrays keep the volume to ~1k rows/day.
--
-- Timing is labelled by what it is:
--   first_seen_at     when OUR fetch received it (not a publication time)
--   ref_run_init      the reference global model's latest run initialisation,
--   ref_run_available and when Open-Meteo made it available, read from the
--                     model's meta.json at fetch time. For the "seamless"
--                     blends (gfs_seamless, icon_seamless) this is the global
--                     component's run, NOT a full description of the blend —
--                     run_meta_source names which model it came from. Null
--                     when the meta fetch failed; never back-filled by guess.
create table if not exists weather_forecast_vintages (
  site_id            text        not null,   -- '<region>:<lat>,<lon>'
  region             text        not null,
  lat                numeric(6,2) not null,
  lon                numeric(6,2) not null,
  model              text        not null,
  variable           text        not null default 'wind_speed_100m',
  unit               text        not null default 'km/h',
  valid_start        timestamptz not null,
  step_seconds       int         not null default 3600 check (step_seconds > 0),
  vals               real[]      not null,   -- nulls kept as nulls, never 0
  series_sha256      text        not null,
  first_seen_at      timestamptz not null default now(),
  ref_run_init       timestamptz,
  ref_run_available  timestamptz,
  run_meta_source    text,
  primary key (site_id, model, variable, valid_start, series_sha256)
);

create index if not exists weather_forecast_vintages_seen_idx
  on weather_forecast_vintages (model, first_seen_at desc);

alter table weather_forecast_vintages enable row level security;
revoke all on weather_forecast_vintages from anon, authenticated;

create or replace function weather_forecast_vintages_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'weather_forecast_vintages is append-only';
end $$;
drop trigger if exists weather_forecast_vintages_guard on weather_forecast_vintages;
create trigger weather_forecast_vintages_guard
  before update or delete on weather_forecast_vintages
  for each row execute function weather_forecast_vintages_guard();
