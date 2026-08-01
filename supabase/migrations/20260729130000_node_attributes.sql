-- Node reference attributes derived from ERCOT documents that no API exposes.
--
-- Three sources, in descending order of how much they can be trusted:
--
--   psse_bus        ERCOT's own Settlement_Points file maps every resource node
--                   to exactly one PSS/E bus. 1,027 of 1,027, no fuzzy matching.
--                   Treat as authoritative.
--
--   county_ercot    From the PSS/E model's zone name (E_<COUNTY>). Authoritative
--                   where present, but some zones encode the operating utility
--                   rather than physical geography, so a handful are wrong.
--
--   tech_class      From the GIS interconnection queue, joined via the bus
--                   number embedded in POI Location. Only covers projects that
--                   went through the modern queue, so older plants are null.
--
--   lat/lon         Fuzzy name matching against USGS/EIA/OSM. Measured at 51%
--                   accuracy overall against ERCOT's own county; 79% within
--                   40km for the high-confidence tier. `location_tier` records
--                   which: A = coordinates confirmed against ERCOT county,
--                   B = county centroid only, C = coordinates unverifiable,
--                   D = no location. Do not use C or D for anything that
--                   depends on position being right.

create table if not exists node_attributes (
  settlement_point  text primary key,
  psse_bus          text,
  load_zone         text,
  substation        text,
  county_ercot      text,
  county_gis        text,
  tech_class        text,
  gis_mw            numeric,
  latitude          numeric,
  longitude         numeric,
  location_tier     text,
  location_source   text,
  updated_at        timestamptz not null default now()
);

create index if not exists node_attributes_tech_idx on node_attributes (tech_class);
create index if not exists node_attributes_zone_idx on node_attributes (load_zone);
create index if not exists node_attributes_tier_idx on node_attributes (location_tier);

-- Generation energising in the interconnection queue, mapped to tradeable
-- nodes through the same POI bus join. `cod` is ERCOT's *projected* commercial
-- operation date and slips routinely — it is a plan, not an event.
create table if not exists node_energizations (
  id                bigserial primary key,
  settlement_point  text not null,
  project_name      text,
  fuel              text,
  capacity_mw       numeric,
  county            text,
  cod               date,
  poi_location      text,
  ingested_at       timestamptz not null default now()
);

create index if not exists node_energizations_sp_idx  on node_energizations (settlement_point);
create index if not exists node_energizations_cod_idx on node_energizations (cod);

alter table node_attributes    enable row level security;
alter table node_energizations enable row level security;

-- The dashboard reads these with the anon key. Reads only: the loader writes
-- as the postgres role and bypasses RLS. Granting select without enabling RLS
-- would leave insert/update/delete open to the public key.
drop policy if exists node_attributes_read on node_attributes;
create policy node_attributes_read on node_attributes for select using (true);

drop policy if exists node_energizations_read on node_energizations;
create policy node_energizations_read on node_energizations for select using (true);

grant select on node_attributes, node_energizations to anon, authenticated;
