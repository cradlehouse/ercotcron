-- Generation interconnection queue: the GIS Report, monthly.
--
-- Every generation project seeking interconnection — county, fuel, MW,
-- point of interconnection, projected COD, study milestones. This is the
-- supply-side complement to transmission_projects: a node's future basis is
-- shaped by what plugs in next to it, and the queue knows years early.
--
-- Source: MIS report type 15933 ("GIS Report", EMIL pg7-200-er, Public) at
-- https://www.ercot.com/misapp/GetReports.do?reportTypeId=15933 — same
-- listing/download servlets as CRR (ercot/crr.py). Monthly XLSX; the
-- "Project Details - Large Gen" and "- Small Gen" sheets are parsed.
-- Keyed per report month: projects change size, COD, and phase between
-- reports, and the drift is the information.

create table if not exists interconnection_queue (
  report_month     date not null,      -- first of the report's month
  inr              text not null,      -- interconnection request id, e.g. 24INR0645
  sheet            text not null default 'large',   -- large | small
  project_name     text,
  study_phase      text,               -- GIM Study Phase
  entity           text,               -- interconnecting entity
  poi_location     text,               -- free text; station names, sometimes coordinates
  county           text,
  zone             text,               -- CDR reporting zone
  projected_cod    date,
  fuel             text,
  technology       text,
  capacity_mw      numeric,
  screening_started    date,
  screening_complete   date,
  fis_requested        date,
  fis_approved         date,
  ia_signed            date,
  construction_start   date,
  construction_end     date,
  approved_energization    date,
  approved_synchronization date,
  comment          text,
  ingested_at      timestamptz not null default now(),
  primary key (report_month, inr)
);

create index if not exists interconnection_queue_county_idx
  on interconnection_queue (county);
create index if not exists interconnection_queue_cod_idx
  on interconnection_queue (projected_cod);
create index if not exists interconnection_queue_fuel_idx
  on interconnection_queue (fuel);

alter table interconnection_queue enable row level security;
drop policy if exists interconnection_queue_read on interconnection_queue;
create policy interconnection_queue_read on interconnection_queue
  for select using (true);
grant select on interconnection_queue to anon, authenticated;
