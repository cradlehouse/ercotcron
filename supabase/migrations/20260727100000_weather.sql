-- Restored filename. This version IS recorded as applied in production.
--
-- The original applied successfully on 27 Jul; a display bug in /stats (the
-- table was never in its list, and absent-from-response rendered as ABSENT)
-- made it look failed, so the file was re-stamped to 20260727120000 and this
-- one deleted. Production then held an applied version with no matching local
-- file, and the migration runner refused every migration since — which is the
-- real reason the signals and crr_bids migrations never landed.
--
-- The runner only needs the version present; the content below is the original
-- and fully idempotent, so a replay on a preview branch is a no-op.

create table if not exists weather_forecast (
  interval_start   timestamptz not null,
  region           text        not null,
  model            text        not null,
  wind_speed_100m  numeric(8,2),
  fetched_at       timestamptz not null default now(),
  primary key (interval_start, region, model)
);

create index if not exists weather_forecast_region_idx
  on weather_forecast (region, interval_start desc);

create or replace function wind_power_fraction(kmh numeric)
returns numeric language sql immutable as $$
  select case
    when kmh is null then null
    when kmh / 3.6 < 3  then 0
    when kmh / 3.6 > 25 then 0
    when kmh / 3.6 >= 12 then 1
    else power((kmh / 3.6 - 3) / 9.0, 3)
  end::numeric;
$$;

create or replace view weather_uncertainty as
select interval_start,
       region,
       count(*)                                                  as models,
       round(avg(wind_speed_100m), 2)                            as mean_speed_kmh,
       round(max(wind_speed_100m) - min(wind_speed_100m), 2)     as speed_spread_kmh,
       round(avg(wind_power_fraction(wind_speed_100m)), 4)       as mean_power_fraction,
       round(max(wind_power_fraction(wind_speed_100m))
           - min(wind_power_fraction(wind_speed_100m)), 4)       as power_spread
  from weather_forecast
 group by 1, 2
having count(*) >= 2;

grant select on weather_forecast, weather_uncertainty to anon, authenticated;
grant execute on function wind_power_fraction(numeric) to anon, authenticated;
