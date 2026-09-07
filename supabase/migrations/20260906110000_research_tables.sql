-- Schema-drift repair (Sep 2026 review #6): dam_constraints, ruc_constraints,
-- resource_outages and the view constraint_novelty were created ad hoc by
-- backfill scripts and existed only in prod — 20260906120000 then indexed a
-- table no migration creates, so a fresh environment failed. DDL below is
-- dumped from prod 2026-09-07; timestamped before the indexing migration so
-- a rebuild sorts correctly, and every statement is idempotent so re-applying
-- to prod is a no-op.

create table if not exists dam_constraints (
  delivery_date  date not null,
  hour_ending    integer not null,
  constraint_id  integer not null,
  constraint_name text not null,
  contingency    text not null default '',
  limit_mw numeric, value_mw numeric, violated_mw numeric, shadow_price numeric,
  from_station text, to_station text, from_kv numeric, to_kv numeric,
  ingested_at timestamptz not null default now(),
  primary key (delivery_date, hour_ending, constraint_id, contingency)
);
create index if not exists dam_constraints_name_idx on dam_constraints (constraint_name);

create table if not exists ruc_constraints (
  delivery_date  date not null,
  hour_ending    integer not null,
  constraint_id  integer not null,
  constraint_name text not null,
  contingency    text not null default '',
  limit_mw numeric, value_mw numeric, violated_mw numeric, shadow_price numeric,
  from_station text, to_station text, from_kv numeric, to_kv numeric,
  ingested_at timestamptz not null default now(),
  primary key (delivery_date, hour_ending, constraint_id, contingency)
);
create index if not exists ruc_constraints_name_idx on ruc_constraints (constraint_name);

create table if not exists resource_outages (
  report_date   date not null,
  resource_name text not null,
  unit_code     text not null,
  fuel_type text, outage_type text,
  max_mw numeric, available_mw numeric, reduction_mw numeric,
  outage_start timestamptz not null,
  planned_end  timestamptz,
  ingested_at  timestamptz not null default now(),
  primary key (report_date, resource_name, unit_code, outage_start)
);
create index if not exists resource_outages_start_idx on resource_outages (outage_start);

alter table dam_constraints enable row level security;
alter table ruc_constraints enable row level security;
alter table resource_outages enable row level security;

-- Which constraints changed their limits recently (re-rates) joined to the
-- registry's liveness view — the "grid changed near this path" signal that
-- seven strategy files read.
create or replace view constraint_novelty as
with limits as (
  select constraint_name,
         date_trunc('week', sced_timestamp) as wk,
         percentile_cont(0.5) within group (order by limit_mw::double precision) as med_limit
    from binding_constraints
   where limit_mw > 0 and limit_mw < 90000
   group by 1, 2
), steps as (
  select constraint_name, wk, med_limit,
         lag(med_limit) over (partition by constraint_name order by wk) as prev
    from limits
), rerate as (
  select constraint_name,
         max(wk) filter (where abs(med_limit - prev) / nullif(prev, 0) > 0.05) as last_rerate,
         count(*) filter (where abs(med_limit - prev) / nullif(prev, 0) > 0.05) as n_rerates
    from steps
   group by 1
), energ as (
  select e.settlement_point, min(e.cod) as next_cod, sum(e.capacity_mw) as mw
    from node_energizations e
   where e.cod >= current_date - interval '90 days'
   group by 1
)
select r.constraint_name, cr.status, cr.binding_hours, cr.last_seen,
       r.last_rerate, coalesce(r.n_rerates, 0) as n_rerates,
       r.last_rerate > (current_date - interval '90 days') as recent_rerate,
       cr.possibly_retired
  from rerate r
  join constraint_registry cr on cr.constraint_name = r.constraint_name;
