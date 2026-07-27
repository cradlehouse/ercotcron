-- Fundamentals: why a price was what it was.
--
-- Price is set by the marginal generator, and what decides which generator that
-- is, hour by hour, is net load — demand minus wind minus solar. Congestion
-- then moves prices apart between locations. These three tables are those two
-- forces: the supply/demand balance, and the constraints that bind.

-- ------------------------------------------------------------------ wind --

-- ERCOT re-forecasts every delivery hour many times before it arrives, which is
-- why two years is 3.8M rows at source. Only the newest vintage per hour is
-- stored: `actual_mw` is null until the hour settles, so the final vintage
-- carries both the outturn and the last forecast made before it.
--
-- The consequence worth knowing: this table answers "what happened and what did
-- we finally expect", not "what did we expect a week out". Forecast-revision
-- history would need posted_at in the key and roughly 200x the rows.
create table if not exists wind_power (
  interval_start  timestamptz not null,
  delivery_date   date        not null,
  hour_ending     smallint    not null,
  region          text        not null,   -- SystemWide, Panhandle, Coastal, South, West, North
  actual_mw       numeric(12,2),          -- null for hours not yet delivered
  forecast_mw     numeric(12,2),          -- STWPF, the headline short-term forecast
  forecast_p80_mw numeric(12,2),          -- WGRPP; the gap to forecast_mw is uncertainty
  cop_hsl_mw      numeric(12,2),
  posted_at       timestamptz,
  ingested_at     timestamptz not null default now(),
  primary key (interval_start, region)
);

create index if not exists wind_power_date_idx on wind_power (delivery_date desc);

create table if not exists solar_power (
  interval_start  timestamptz not null,
  delivery_date   date        not null,
  hour_ending     smallint    not null,
  region          text        not null,
  actual_mw       numeric(12,2),
  forecast_mw     numeric(12,2),
  forecast_p80_mw numeric(12,2),
  cop_hsl_mw      numeric(12,2),
  posted_at       timestamptz,
  ingested_at     timestamptz not null default now(),
  primary key (interval_start, region)
);

create index if not exists solar_power_date_idx on solar_power (delivery_date desc);

-- ------------------------------------------------------------------ load --

-- Weather zones, not load zones. `far_west` here is a weather geography and is
-- NOT the LZ_WEST settlement point — different boundaries for different
-- purposes. Any join between the two is an approximation.
create table if not exists load_forecast (
  interval_start timestamptz not null,
  delivery_date  date        not null,
  hour_ending    smallint    not null,
  zone           text        not null,   -- coast, east, farWest, ..., systemTotal
  forecast_mw    numeric(12,2),
  posted_at      timestamptz,
  ingested_at    timestamptz not null default now(),
  primary key (interval_start, zone)
);

create index if not exists load_forecast_date_idx on load_forecast (delivery_date desc);

-- ----------------------------------------------------------- constraints --

-- Every binding transmission constraint per SCED run, with the shadow price —
-- the marginal cost of the congestion it caused. This is the causal layer under
-- a CRR: a path is valuable because some constraint binds, and this says which,
-- how often, and how hard.
create table if not exists binding_constraints (
  sced_timestamp   timestamptz not null,
  constraint_id    integer     not null,
  contingency      text        not null,
  constraint_name  text,
  shadow_price     numeric(14,4),
  max_shadow_price numeric(14,4),
  limit_mw         numeric(14,4),
  value_mw         numeric(14,4),
  violated_mw      numeric(14,4),
  from_station     text,
  to_station       text,
  from_kv          numeric(10,2),
  to_kv            numeric(10,2),
  cct_status       text,
  ingested_at      timestamptz not null default now(),
  -- One SCED run can bind the same constraint under different contingencies,
  -- so the contingency is part of the identity, not a detail.
  primary key (sced_timestamp, constraint_id, contingency)
);

create index if not exists binding_constraints_time_idx  on binding_constraints (sced_timestamp desc);
create index if not exists binding_constraints_name_idx  on binding_constraints (constraint_name);
create index if not exists binding_constraints_price_idx on binding_constraints (shadow_price desc);

-- -------------------------------------------------------------- net load --

-- The spine: demand minus renewables, against what power actually cost. Uses
-- SystemWide wind and solar against the systemTotal load forecast, so it is a
-- system-level view — locational effects live in the constraint and path
-- tables, not here.
create or replace view net_load as
select l.interval_start,
       l.delivery_date,
       l.hour_ending,
       l.forecast_mw                                    as load_mw,
       w.actual_mw                                      as wind_mw,
       s.actual_mw                                      as solar_mw,
       l.forecast_mw - coalesce(w.actual_mw, 0) - coalesce(s.actual_mw, 0)
                                                        as net_load_mw,
       w.forecast_mw                                    as wind_forecast_mw,
       -- Forecast error is signed: positive means more wind blew than expected,
       -- which is the direction that pushes prices down.
       w.actual_mw - w.forecast_mw                      as wind_miss_mw
  from load_forecast l
  left join wind_power  w on w.interval_start = l.interval_start and w.region = 'SystemWide'
  left join solar_power s on s.interval_start = l.interval_start and s.region = 'SystemWide'
 where l.zone = 'systemTotal';

grant select on wind_power, solar_power, load_forecast, binding_constraints, net_load
   to anon, authenticated;
