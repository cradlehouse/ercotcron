-- The novelty-control layer's state table. Every constraint ever observed
-- binding, its observation depth, and its status in the exposure map:
--
--   candidate   seen, not yet enough independent observations to trust betas
--   promoted    exposure map may be used for DIRECTION (never sizing)
--   restricted  failed stability or diagnostics (1025__B, 6830__B)
--   retired     no binding observed for 120+ days — likely reconfigured away;
--               betas must not be used and history predating retirement must
--               not be revived if the name reappears (treat as new)
--
-- Status changes are recorded, never overwritten: audit trail matters more
-- than tidiness here, because "when did we start trusting X" is exactly the
-- question a post-mortem asks.
create table if not exists constraint_registry (
  constraint_name  text primary key,
  first_seen       date not null,
  last_seen        date not null,
  binding_hours    int  not null,
  distinct_days    int  not null,
  status           text not null default 'candidate',
  status_reason    text,
  status_since     timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table if not exists constraint_status_log (
  id              bigserial primary key,
  constraint_name text not null,
  old_status      text,
  new_status      text not null,
  reason          text,
  changed_at      timestamptz not null default now()
);

alter table constraint_registry  enable row level security;
alter table constraint_status_log enable row level security;
drop policy if exists constraint_registry_read on constraint_registry;
create policy constraint_registry_read on constraint_registry for select using (true);
drop policy if exists constraint_status_log_read on constraint_status_log;
create policy constraint_status_log_read on constraint_status_log for select using (true);
grant select on constraint_registry, constraint_status_log to anon, authenticated;
