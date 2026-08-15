-- Market intelligence layer: qualitative knowledge with provenance, linkage,
-- and expiry. Append-only (same discipline as negative_knowledge/mark_runs):
-- items are superseded or falsified by NEW rows, never edited.
-- Intel ANNOTATES valuations and bids; it never changes a computed number.

create table if not exists market_intel (
  intel_id     bigint generated always as identity primary key,
  captured_at  timestamptz not null default now(),
  source       text not null,        -- 'steve' | 'tim' | 'ercot-notice' | 'nomcr' | 'tpit' | 'som-report' | 'press' | 'engine' | ...
  source_ref   text,                 -- url / document / conversation date
  claim        text not null,        -- the intelligence, in plain words
  constraints_affected text[] not null default '{}',
  paths_affected       text[] not null default '{}',   -- 'SRC->SNK'
  holders_affected     text[] not null default '{}',
  months_affected      daterange,    -- delivery window the claim bears on
  stance      text not null default 'neutral' check (stance in ('bullish','bearish','neutral','structural')),
  confidence  text not null default 'medium' check (confidence in ('low','medium','high','confirmed')),
  expires_on  date,                  -- intel rots; null = until superseded
  supersedes  bigint references market_intel(intel_id),
  status      text not null default 'active' check (status in ('active','expired','superseded','falsified'))
);

-- AI interpretation pass output: how each intel item bears on a concrete
-- decision object (a candidate bid, a held position, a mark, a counterparty).
create table if not exists intel_impacts (
  intel_id    bigint not null references market_intel(intel_id),
  assessed_at timestamptz not null default now(),
  object_kind text not null check (object_kind in ('bid','position','mark','holder','constraint')),
  object_key  text not null,        -- e.g. 'SRC->SNK|PeakWD|OPT|2026-09' or holder code
  effect      text not null check (effect in ('supports','against','caps-tier','review','informational')),
  note        text not null,        -- one-sentence reasoning, shown in UI
  primary key (intel_id, object_kind, object_key, assessed_at)
);

create or replace function intel_guard() returns trigger
language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'market_intel is append-only'; end if;
  -- only status may change (active -> expired/superseded/falsified)
  if new.claim <> old.claim or new.source <> old.source
     or new.captured_at <> old.captured_at then
    raise exception 'market_intel rows are immutable; supersede with a new row';
  end if;
  return new;
end $$;

drop trigger if exists market_intel_guard on market_intel;
create trigger market_intel_guard
  before update or delete on market_intel
  for each row execute function intel_guard();

alter table market_intel enable row level security;
alter table intel_impacts enable row level security;
