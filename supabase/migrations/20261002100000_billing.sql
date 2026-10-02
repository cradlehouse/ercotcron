-- Billing: Stripe is the system of record for money; profiles.plan stays the
-- one thing every gate reads (has_active_plan(), migration 20260907080000).
--
-- The web tier holds no service key, so Stripe's webhook reaches the
-- database the same way the claim flow does: a security-definer RPC that
-- only acts for callers presenting the server secret (app_secrets
-- 'billing_rpc', mirrored in Vercel as BILLING_RPC_SECRET). A user calling
-- billing_apply directly changes nothing.
--
-- Plan mapping (Stripe subscription status -> plan):
--   trialing, active, past_due      -> 'active'   (past_due = Stripe is
--                                      retrying the card; access holds
--                                      through the retry window)
--   canceled, unpaid,
--   incomplete_expired              -> 'cancelled'
--   incomplete, paused              -> unchanged (first payment pending /
--                                      deliberate pause: neither grants
--                                      nor revokes)
-- 'comp' is never touched — billing ids are recorded, the plan is not.

alter table profiles
  add column if not exists stripe_customer_id text unique,
  add column if not exists stripe_subscription_id text,
  add column if not exists subscription_status text,
  add column if not exists current_period_end timestamptz,
  add column if not exists plan_tier text;

-- Audit trail: every webhook the RPC accepted, append-only, idempotent on
-- Stripe's event id (Stripe redelivers; a replay must be a no-op).
create table if not exists billing_events (
  event_id    text primary key,
  user_id     uuid references auth.users(id) on delete set null,
  type        text not null,
  status      text,
  received_at timestamptz not null default now()
);
alter table billing_events enable row level security;
revoke all on billing_events from public, anon, authenticated;

create or replace function billing_apply(
  p_secret text, p_event_id text, p_type text, p_user_id uuid,
  p_customer text, p_subscription text, p_status text,
  p_period_end timestamptz, p_tier text)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_ok boolean;
  v_plan text;
begin
  select (p_secret is not null and p_secret = value) into v_ok
    from app_secrets where name = 'billing_rpc';
  if not coalesce(v_ok, false) then
    raise exception 'billing_apply: not authorized';
  end if;

  insert into billing_events (event_id, user_id, type, status)
  values (p_event_id, p_user_id, p_type, p_status)
  on conflict (event_id) do nothing;
  if not found then
    return 'duplicate';
  end if;

  if p_user_id is null then
    return 'no-user';
  end if;

  v_plan := case
    when p_status in ('trialing', 'active', 'past_due') then 'active'
    when p_status in ('canceled', 'unpaid', 'incomplete_expired') then 'cancelled'
    else null end;

  update profiles set
    stripe_customer_id     = coalesce(p_customer, stripe_customer_id),
    stripe_subscription_id = coalesce(p_subscription, stripe_subscription_id),
    subscription_status    = coalesce(p_status, subscription_status),
    current_period_end     = coalesce(p_period_end, current_period_end),
    plan_tier              = coalesce(p_tier, plan_tier),
    plan = case when plan = 'comp' or v_plan is null then plan else v_plan end
  where user_id = p_user_id;
  if not found then
    return 'no-profile';
  end if;
  return coalesce(v_plan, 'unchanged');
end $$;
revoke execute on function billing_apply(text, text, text, uuid, text, text, text, timestamptz, text) from public;
grant execute on function billing_apply(text, text, text, uuid, text, text, text, timestamptz, text) to anon, authenticated;

-- The secret row itself is inserted out of band (never committed):
--   insert into app_secrets (name, value) values ('billing_rpc', '<random>')
--   on conflict (name) do update set value = excluded.value;
