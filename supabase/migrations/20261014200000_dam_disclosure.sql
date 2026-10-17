-- 60-Day DAM Disclosure (ERCOT NP3-966-ER): the day-ahead market's own
-- injections and withdrawals, hourly, one row per item per operating day.
--
-- Purpose: the grid replay (docs/GRID_REPLAY_PLAN_2026-10-14.md) needs where
-- power entered and left the network in the market that CRRs settle on.
-- Every row carries an ERCOT settlement point, which maps to PSS/E buses via
-- ERCOT's Settlement_Points file - no name matching.
--
-- Arrays hold hours ending 1..24 (25 on the fall-back day, 23 on spring-
-- forward; array length = hours in that operating day). Nulls are kept as
-- nulls, never 0. Research data: RLS on, no anon/authenticated access.

create table if not exists dam_resource_awards (
  delivery_date     date    not null,
  resource          text    not null,          -- e.g. 7RNCHSLR_UNIT1
  resource_type     text,                      -- PVGR, WIND, CCGT90, ESR ...
  settlement_point  text,
  awarded_mw        real[]  not null,          -- DAM energy award, MW
  hsl_mw            real[],                    -- high sustained limit offered
  status            text[],
  source_posted_at  timestamptz,               -- ERCOT archive postDatetime
  primary key (delivery_date, resource)
);

create table if not exists dam_virtual_awards (
  delivery_date     date    not null,
  settlement_point  text    not null,
  offer_mw          real[]  not null,          -- energy-only offer awards (injection)
  bid_mw            real[]  not null,          -- energy bid awards (withdrawal)
  source_posted_at  timestamptz,
  primary key (delivery_date, settlement_point)
);

create table if not exists dam_ptp_awards (
  delivery_date     date    not null,
  source            text    not null,
  sink              text    not null,
  mw                real[]  not null,          -- PTP obligation/option awards
  source_posted_at  timestamptz,
  primary key (delivery_date, source, sink)
);

alter table dam_resource_awards enable row level security;
alter table dam_virtual_awards  enable row level security;
alter table dam_ptp_awards      enable row level security;
revoke all on dam_resource_awards, dam_virtual_awards, dam_ptp_awards from anon, authenticated;
