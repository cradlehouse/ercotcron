-- Five-minute SCED LMP and RTD forecast vintages.
--
-- Both are partitioned monthly on interval_start. Partitions are created three
-- months ahead by the `partitions` ingest job (Python, not pg_cron — one less
-- moving part, and it reports into ingest_runs like every other job).
--
-- Rows landing in *_default mean that job has stopped. Check it before the
-- default partitions grow large.

-- ------------------------------------------------- 5-minute SCED LMP (SPP) --

create table if not exists rt_lmp_5min (
  settlement_point text        not null,
  interval_start   timestamptz not null,
  sced_timestamp   timestamptz not null,
  price            numeric(14,4) not null,
  energy           numeric(14,4),
  congestion       numeric(14,4),
  loss             numeric(14,4),
  dst_flag         boolean     not null default false,
  posted_at        timestamptz,
  price_from       timestamptz not null default now(),
  ingested_at      timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  primary key (settlement_point, interval_start)
) partition by range (interval_start);

create table if not exists rt_lmp_5min_default
  partition of rt_lmp_5min default;

create index if not exists rt_lmp_5min_interval_idx
  on rt_lmp_5min (interval_start desc);

create table if not exists rt_lmp_5min_history (
  history_id       bigserial primary key,
  settlement_point text        not null,
  interval_start   timestamptz not null,
  sced_timestamp   timestamptz not null,
  price            numeric(14,4) not null,
  energy           numeric(14,4),
  congestion       numeric(14,4),
  loss             numeric(14,4),
  dst_flag         boolean     not null default false,
  posted_at        timestamptz,
  price_from       timestamptz not null,
  price_to         timestamptz not null,
  ingested_at      timestamptz not null
);

create index if not exists rt_lmp_5min_history_key_idx
  on rt_lmp_5min_history (settlement_point, interval_start, price_from desc);

drop trigger if exists rt_lmp_5min_revision on rt_lmp_5min;
create trigger rt_lmp_5min_revision before update on rt_lmp_5min
  for each row execute function capture_price_revision('rt_lmp_5min_history');

-- ------------------------------------------------------ RTD forecast LMP --

-- Many run times (rtd_timestamp) produce a forecast for the same target
-- interval. Each vintage is its own row, so there is nothing to revise and no
-- revision trigger — the key includes rtd_timestamp.
create table if not exists rtd_lmp (
  settlement_point text        not null,
  interval_start   timestamptz not null,
  rtd_timestamp    timestamptz not null,
  price            numeric(14,4) not null,
  energy           numeric(14,4),
  congestion       numeric(14,4),
  loss             numeric(14,4),
  dst_flag         boolean     not null default false,
  posted_at        timestamptz,
  ingested_at      timestamptz not null default now(),
  primary key (settlement_point, interval_start, rtd_timestamp)
) partition by range (interval_start);

create table if not exists rtd_lmp_default
  partition of rtd_lmp default;

create index if not exists rtd_lmp_interval_idx on rtd_lmp (interval_start desc);
create index if not exists rtd_lmp_run_idx      on rtd_lmp (rtd_timestamp desc);

-- ------------------------------------------------- partition maintenance --

-- Create the monthly partition covering p_month for a partitioned table, if it
-- does not exist. Idempotent; safe to call on every scheduler tick.
create or replace function ensure_month_partition(p_table text, p_month date)
returns text language plpgsql as $$
declare
  start_ts date := date_trunc('month', p_month)::date;
  end_ts   date := (date_trunc('month', p_month) + interval '1 month')::date;
  part     text := format('%s_%s', p_table, to_char(start_ts, 'YYYYMM'));
begin
  if to_regclass(part) is null then
    execute format(
      'create table %I partition of %I for values from (%L) to (%L)',
      part, p_table, start_ts, end_ts);
  end if;
  return part;
end $$;

-- Turn partitions ending before p_before into standalone tables that can be
-- dumped and dropped without locking live data. This is the seam for a Parquet
-- cold tier; nothing consumes it yet.
create or replace function detach_partitions_before(p_before date)
returns setof text language plpgsql as $$
declare
  r record;
begin
  for r in
    select parent.relname as parent, child.relname as child,
           pg_get_expr(child.relpartbound, child.oid) as bound
      from pg_inherits
      join pg_class parent on parent.oid = pg_inherits.inhparent
      join pg_class child  on child.oid  = pg_inherits.inhrelid
     where parent.relname in ('rt_lmp_5min', 'rtd_lmp')
       and child.relname not like '%\_default'
  loop
    if r.bound ~ 'TO \(''(\d{4}-\d{2}-\d{2})' then
      if (regexp_match(r.bound, 'TO \(''(\d{4}-\d{2}-\d{2})'))[1]::date <= p_before then
        execute format('alter table %I detach partition %I', r.parent, r.child);
        return next r.child;
      end if;
    end if;
  end loop;
end $$;
