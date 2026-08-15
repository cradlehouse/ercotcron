-- Transmission Project Information Tracking (TPIT): where the wires are going.
--
-- ERCOT's quarterly-ish workbook of every transmission project 60kV+ with a
-- material impact on power flow — in-service dates, counties, voltage, status.
-- A constraint's remaining lifetime is a transmission project's construction
-- schedule; congestion positions priced without this are priced on the
-- assumption the grid never changes.
--
-- Source: the "Transmission Project and Information Tracking" link on
-- https://www.ercot.com/gridinfo/planning (EMIL zp8-801-m, Public). The file
-- URL and name change with each release, so ingest scrapes the page anchor.
-- Rows are keyed by release: each report_date is a full snapshot, because
-- projects move between sheets (Future -> Planned -> Completed/Cancelled) and
-- the movement itself is the signal.

create table if not exists transmission_projects (
  report_date          date not null,   -- release date embedded in the sheet names
  sheet                text not null,   -- future | planned | completed | cancelled
  project_number       text not null,   -- ERCOT Project Number
  phase                text not null default '',
  title                text,
  description          text,
  comments             text,            -- reasons for delays/changes — free text, often the story
  from_location        text,
  to_location          text,
  status               text,            -- Planned / Under Construction / In-Service / Conceptual
  owner                text,            -- TSP short name (ONCOR, CNP, STEC, ...)
  owner_project        text,
  projected_in_service date,
  actual_in_service    date,
  voltage_kv           numeric,
  miles_new            numeric,
  miles_rebuilt        numeric,
  autotransformer_mva  numeric,
  reactive_mvar        numeric,         -- negative = reactor, positive = capacitor
  county_from          text,
  county_to            text,
  tier                 text,            -- Planning Charter Tier
  rpg_number           text,
  ingested_at          timestamptz not null default now(),
  primary key (report_date, sheet, project_number, phase)
);

create index if not exists transmission_projects_county_idx
  on transmission_projects (county_from);
create index if not exists transmission_projects_inservice_idx
  on transmission_projects (projected_in_service);

alter table transmission_projects enable row level security;
drop policy if exists transmission_projects_read on transmission_projects;
create policy transmission_projects_read on transmission_projects
  for select using (true);
grant select on transmission_projects to anon, authenticated;
