-- Market notices: the public trace of network model changes.
--
-- Full NOMCR detail (NP3-107-UI and its status/summary reports) is Certified
-- on the secure MIS — market participants only, via ModelEditor/EWS. What IS
-- public is the ERCOT market notice archive: every notice ERCOT sends about
-- model loads, topology changes, GTC retirements, constraint methodology and
-- system maintenance, with a rolling ~3-year window at
-- https://www.ercot.com/services/comm/mkt_notices/archives (server-rendered
-- HTML; detail pages at /services/comm/mkt_notices/<notice_id>).
--
-- We ingest the whole notice stream and flag the model-related subset, rather
-- than filtering at ingest: the archive is small (hundreds of rows a year),
-- the keyword list will change, and a notice discarded at ingest is gone when
-- the window rolls past it.

create table if not exists model_change_notices (
  notice_id        text primary key,   -- e.g. M-A081026-02 (corrections reuse the id; last wins)
  posted_at        date not null,
  title            text not null,
  notice_type      text,
  audience         text,
  days_affected    text,               -- raw DAYS AFFECTED field
  effective_date   date,               -- first parseable date in days_affected, if any
  body             text,               -- LONG DESCRIPTION, plain text
  url              text not null,
  is_model_related boolean not null default false,
  ingested_at      timestamptz not null default now()
);

create index if not exists model_change_notices_posted_idx
  on model_change_notices (posted_at);
create index if not exists model_change_notices_model_idx
  on model_change_notices (is_model_related) where is_model_related;

alter table model_change_notices enable row level security;
drop policy if exists model_change_notices_read on model_change_notices;
create policy model_change_notices_read on model_change_notices
  for select using (true);
grant select on model_change_notices to anon, authenticated;
