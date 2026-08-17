-- Product data structures for the rebuilt member area (SITE_ARCHITECTURE §4).

-- Which CRRAH codes an account may see. Admin-granted; this is the
-- per-holder privacy rule enforced at the database.
create table if not exists user_holders (
  user_id     uuid not null references auth.users(id) on delete cascade,
  holder_code text not null,
  granted_at  timestamptz not null default now(),
  granted_by  text,
  primary key (user_id, holder_code)
);
alter table user_holders enable row level security;
drop policy if exists "own grants" on user_holders;
create policy "own grants" on user_holders for select using (auth.uid() = user_id);

-- Per-user watched paths and constraints; drives alerts and "your paths".
create table if not exists watchlists (
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in ('path','constraint')),
  key        text not null,          -- 'SRC->SNK|TOU|HEDGE' or constraint name
  created_at timestamptz not null default now(),
  primary key (user_id, kind, key)
);
alter table watchlists enable row level security;
drop policy if exists "own watchlist" on watchlists;
create policy "own watchlist" on watchlists
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Alert events (from intel/novelty touching watched entities) and deliveries.
create table if not exists alert_events (
  event_id   bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  kind       text not null,          -- 'constraint-rerate' | 'intel' | 'relief-project' | ...
  entity     text not null,          -- constraint name or path key
  headline   text not null,
  detail     text,
  source_ref text                    -- intel_id / novelty row / run id
);
create table if not exists alert_deliveries (
  event_id     bigint not null references alert_events(event_id),
  user_id      uuid not null references auth.users(id) on delete cascade,
  delivered_at timestamptz,
  channel      text not null default 'app' check (channel in ('app','email')),
  seen_at      timestamptz,
  primary key (event_id, user_id, channel)
);
alter table alert_events enable row level security;
alter table alert_deliveries enable row level security;
drop policy if exists "events readable" on alert_events;
create policy "events readable" on alert_events for select using (true);
drop policy if exists "own deliveries" on alert_deliveries;
create policy "own deliveries" on alert_deliveries
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Published bid-sheet editions: the sheet becomes a versioned artifact.
create table if not exists sheets (
  sheet_id     bigint generated always as identity primary key,
  auction_name text not null,
  edition      int not null default 1,
  status       text not null default 'draft' check (status in ('draft','published','scored')),
  published_at timestamptz,
  run_ref      text,                 -- valuation run / computed_at marker
  notes        text,
  unique (auction_name, edition)
);
alter table sheets enable row level security;
drop policy if exists "sheets readable" on sheets;
create policy "sheets readable" on sheets for select using (true);
