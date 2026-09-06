-- Outreach suppression list (legal review A17, CAN-SPAM): anyone who opts
-- out is recorded here append-only, and every future send checks it first.
-- Rows are written only through the server-verified route (HMAC-signed
-- unsubscribe links), via the same server-secret pattern as claim_holder.
create table if not exists email_suppression (
  id bigint generated always as identity primary key,
  email text not null,
  reason text not null default 'unsubscribe',
  created_at timestamptz not null default now()
);
create unique index if not exists email_suppression_email_idx
  on email_suppression (lower(email));
alter table email_suppression enable row level security;
revoke all on email_suppression from anon, authenticated;

create or replace function email_suppression_guard() returns trigger
language plpgsql as $$
begin
  raise exception 'email_suppression is append-only';
end $$;
drop trigger if exists email_suppression_guard on email_suppression;
create trigger email_suppression_guard
  before update or delete on email_suppression
  for each row execute function email_suppression_guard();

create or replace function record_suppression(p_email text, p_server_secret text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from app_secrets
                  where name = 'claim_rpc' and value = p_server_secret) then
    raise exception 'not authorized';
  end if;
  insert into email_suppression (email) values (lower(trim(p_email)))
  on conflict (lower(email)) do nothing;
end $$;

revoke execute on function record_suppression(text, text) from public, anon, authenticated;
grant execute on function record_suppression(text, text) to anon, authenticated;
-- (grant needed so the API route's anon-key client can call it; the server
-- secret argument is the actual gate.)
