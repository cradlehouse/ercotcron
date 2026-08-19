-- Generated-data store: platform jobs write here, the web reads here.
-- Replaces JSON files committed to the repo (nothing runs locally anymore).
create table if not exists artifacts (
  name       text primary key,
  body       jsonb not null,
  updated_at timestamptz not null default now(),
  built_by   text                    -- job name / seed
);
alter table artifacts enable row level security;
drop policy if exists "artifacts readable" on artifacts;
create policy "artifacts readable" on artifacts for select using (true);
grant select on artifacts to anon, authenticated;
