-- Independent weather forecasts, and how much the models disagree.
--
-- ERCOT publishes one wind forecast and no measure of its own confidence. Three
-- global models (ECMWF, GFS, ICON) forecasting the same hour give that missing
-- number: when they diverge, the atmosphere is genuinely uncertain, and so is
-- the price.
--
-- Measured on Panhandle sites, July 2026: the models disagree by 9 km/h on an
-- average hour, which is 30% of wind capacity once run through a power curve,
-- and up to 96% on the worst hours.

create table if not exists weather_forecast (
  interval_start   timestamptz not null,
  region           text        not null,   -- matches wind_power.region
  model            text        not null,   -- ecmwf_ifs025 | gfs_seamless | icon_seamless
  wind_speed_100m  numeric(8,2),           -- km/h at hub height, capacity-weighted across sites
  fetched_at       timestamptz not null default now(),
  primary key (interval_start, region, model)
);

create index if not exists weather_forecast_region_idx
  on weather_forecast (region, interval_start desc);

-- Power curve: cut-in 3 m/s, rated 12, cut-out 25, cubic between cut-in and
-- rated. A generic turbine, not ERCOT's actual fleet — the real aggregate curve
-- is smoother because the fleet is heterogeneous and geographically spread, so
-- treat the amplification this implies as an upper bound.
--
-- The shape is the point: a 10% speed error is worth 1.7% of capacity at 5 m/s
-- and 53% at 11 m/s. Error only matters in the ramp.
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

-- Per hour and region: where the models sit, and how far apart. power_spread is
-- the tradeable number — speed disagreement matters only insofar as it becomes
-- generation disagreement.
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
