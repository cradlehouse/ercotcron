-- Audit trail for the valuation (marks) engine — methodology §8.
-- Append-only: no updates or deletes; corrections are new runs.

create table if not exists mark_runs (
  run_id        bigint generated always as identity primary key,
  run_at        timestamptz not null default now(),
  engine_sha    text not null,             -- git commit of the engine code
  methodology_v text not null,             -- e.g. '1.0' (docs/MARK_METHODOLOGY.md)
  input_watermarks jsonb not null,         -- {table: {max_ingested_at, row_count}, ...}
  params        jsonb not null default '{}'::jsonb,  -- thresholds/trims in force
  published_by  text,
  reviewed_by   text,
  notes         text
);

create table if not exists marks (
  run_id         bigint not null references mark_runs(run_id),
  account_holder text not null,
  source         text not null,
  sink           text not null,
  time_of_use    text not null,
  hedge_type     text not null,
  start_date     date not null,
  end_date       date not null,
  mw             numeric not null,
  rate_per_mwh   numeric,                  -- pre-trim calendar-month rate
  hours          integer,
  trims          jsonb not null default '[]'::jsonb,  -- [{name, trigger, pct}, ...]
  flags          text[] not null default '{}',        -- LOW_HISTORY, STALE_DRIVER, ...
  mark_value     numeric,                  -- final trimmed $ value
  clearing_basis numeric,                  -- avg of last 3 monthly-auction clears
  primary key (run_id, account_holder, source, sink, time_of_use, hedge_type, start_date, end_date)
);

-- Enforce append-only at the database level.
create or replace function reject_mutation() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'append-only table: % on % is not allowed', tg_op, tg_table_name;
end $$;

drop trigger if exists mark_runs_append_only on mark_runs;
create trigger mark_runs_append_only
  before update or delete on mark_runs
  for each row execute function reject_mutation();

drop trigger if exists marks_append_only on marks;
create trigger marks_append_only
  before update or delete on marks
  for each row execute function reject_mutation();

alter table mark_runs enable row level security;
alter table marks enable row level security;
