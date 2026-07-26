-- ERCOT pricing platform — core tables.
--
-- Bitemporal by design: ERCOT revises published prices. Every price row records
-- when the power flowed (interval_start), when ERCOT published (posted_at), when
-- this value took effect in our store (price_from) and when we first saw the row
-- (ingested_at, immutable). Superseded values move to *_history so a backtest can
-- reconstruct what was knowable at any past moment.
--
-- Backtests must read through rt_spp_asof() / dam_spp_asof(), never the live tables.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- catalogue --

create table if not exists settlement_points (
  name           text primary key,
  point_type     text,            -- HU / LZ / SH / RN / etc.
  zone           text,
  active         boolean     not null default true,
  first_seen_at  timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

comment on table settlement_points is
  'Catalogue of ERCOT settlement points. Deliberately not a foreign key target: '
  'ERCOT introduces new points and ingest must never reject a price for an '
  'unknown one.';

-- -------------------------------------------------------------- ingest runs --

create table if not exists ingest_runs (
  id             bigserial primary key,
  job            text        not null,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         text        not null default 'running'
                 check (status in ('running','ok','error','empty')),
  window_start   timestamptz,
  window_end     timestamptz,
  requests       integer     not null default 0,
  rows_seen      integer     not null default 0,
  rows_inserted  integer     not null default 0,
  rows_revised   integer     not null default 0,
  error          text
);

create index if not exists ingest_runs_job_started_idx
  on ingest_runs (job, started_at desc);

comment on column ingest_runs.status is
  'empty means the request succeeded but returned no rows — the signature of a '
  'wrong query parameter name, which ERCOT does not report as an error.';

-- ------------------------------------------------------ day-ahead SPP (DAM) --

create table if not exists dam_spp (
  settlement_point text        not null,
  interval_start   timestamptz not null,
  delivery_date    date        not null,
  hour_ending      smallint    not null,
  price            numeric(14,4) not null,
  dst_flag         boolean     not null default false,
  posted_at        timestamptz,
  price_from       timestamptz not null default now(),
  ingested_at      timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  primary key (settlement_point, interval_start)
);

create index if not exists dam_spp_interval_idx on dam_spp (interval_start desc);
create index if not exists dam_spp_date_idx     on dam_spp (delivery_date desc);

create table if not exists dam_spp_history (
  history_id       bigserial primary key,
  settlement_point text        not null,
  interval_start   timestamptz not null,
  delivery_date    date        not null,
  hour_ending      smallint    not null,
  price            numeric(14,4) not null,
  dst_flag         boolean     not null default false,
  posted_at        timestamptz,
  price_from       timestamptz not null,
  price_to         timestamptz not null,
  ingested_at      timestamptz not null
);

create index if not exists dam_spp_history_key_idx
  on dam_spp_history (settlement_point, interval_start, price_from desc);

-- ------------------------------------------------- real-time 15-minute SPP --

create table if not exists rt_spp (
  settlement_point  text        not null,
  interval_start    timestamptz not null,
  delivery_date     date        not null,
  delivery_hour     smallint    not null,
  delivery_interval smallint    not null,
  price             numeric(14,4) not null,
  dst_flag          boolean     not null default false,
  posted_at         timestamptz,
  price_from        timestamptz not null default now(),
  ingested_at       timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  primary key (settlement_point, interval_start)
);

create index if not exists rt_spp_interval_idx on rt_spp (interval_start desc);
create index if not exists rt_spp_date_idx     on rt_spp (delivery_date desc);

comment on table rt_spp is
  'Intentionally unpartitioned. Fine to roughly three years at current point '
  'coverage; convert to partition-by-delivery_date before it approaches 100M rows.';

create table if not exists rt_spp_history (
  history_id        bigserial primary key,
  settlement_point  text        not null,
  interval_start    timestamptz not null,
  delivery_date     date        not null,
  delivery_hour     smallint    not null,
  delivery_interval smallint    not null,
  price             numeric(14,4) not null,
  dst_flag          boolean     not null default false,
  posted_at         timestamptz,
  price_from        timestamptz not null,
  price_to          timestamptz not null,
  ingested_at       timestamptz not null
);

create index if not exists rt_spp_history_key_idx
  on rt_spp_history (settlement_point, interval_start, price_from desc);

-- ------------------------------------------------------- revision capture --

-- BEFORE UPDATE trigger. Argument 1 is the history table name.
-- Keeps ingested_at immutable, moves a changed price into history, and stamps
-- price_from with the moment the new value took effect here.
create or replace function capture_price_revision() returns trigger
language plpgsql as $$
declare
  hist text := tg_argv[0];
begin
  new.ingested_at := old.ingested_at;

  if new.price is distinct from old.price then
    if hist = 'dam_spp_history' then
      insert into dam_spp_history (settlement_point, interval_start, delivery_date,
                                   hour_ending, price, dst_flag, posted_at,
                                   price_from, price_to, ingested_at)
      values (old.settlement_point, old.interval_start, old.delivery_date,
              old.hour_ending, old.price, old.dst_flag, old.posted_at,
              old.price_from, now(), old.ingested_at);
    elsif hist = 'rt_spp_history' then
      insert into rt_spp_history (settlement_point, interval_start, delivery_date,
                                  delivery_hour, delivery_interval, price, dst_flag,
                                  posted_at, price_from, price_to, ingested_at)
      values (old.settlement_point, old.interval_start, old.delivery_date,
              old.delivery_hour, old.delivery_interval, old.price, old.dst_flag,
              old.posted_at, old.price_from, now(), old.ingested_at);
    elsif hist = 'rt_lmp_5min_history' then
      insert into rt_lmp_5min_history (settlement_point, interval_start, sced_timestamp,
                                       price, energy, congestion, loss, dst_flag,
                                       posted_at, price_from, price_to, ingested_at)
      values (old.settlement_point, old.interval_start, old.sced_timestamp,
              old.price, old.energy, old.congestion, old.loss, old.dst_flag,
              old.posted_at, old.price_from, now(), old.ingested_at);
    else
      raise exception 'capture_price_revision: unknown history table %', hist;
    end if;

    new.price_from := now();
  else
    new.price_from := old.price_from;
  end if;

  new.updated_at := now();
  return new;
end $$;

drop trigger if exists dam_spp_revision on dam_spp;
create trigger dam_spp_revision before update on dam_spp
  for each row execute function capture_price_revision('dam_spp_history');

drop trigger if exists rt_spp_revision on rt_spp;
create trigger rt_spp_revision before update on rt_spp
  for each row execute function capture_price_revision('rt_spp_history');
