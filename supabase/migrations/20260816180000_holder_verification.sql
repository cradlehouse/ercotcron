-- Holder-claim verification (options 1+2):
--   1. registry match — claim auto-approves when the signup email exactly
--      matches, or shares a domain with, the holder's registered ERCOT
--      contact (public CRRAH registry).
--   2. email confirmation — otherwise a one-time token is minted; the app
--      emails an approval link to the REGISTERED address; opening it approves.
-- Manual review remains the fallback for everything else.

create table if not exists crrah_registry (
  holder_code   text primary key,
  contact_email text,
  contact_name  text,
  loaded_at     timestamptz not null default now()
);
alter table crrah_registry enable row level security;  -- no policies: definer-only

create table if not exists holder_verifications (
  token       uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  holder_code text not null,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '7 days',
  used_at     timestamptz
);
alter table holder_verifications enable row level security;  -- definer-only

create or replace function claim_holder(p_code text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_email text;
  v_reg record;
  v_status text := 'pending';
  v_token uuid;
begin
  if v_uid is null then raise exception 'not authenticated'; end if;
  p_code := upper(trim(p_code));
  if p_code !~ '^[A-Z0-9_]{3,12}$' then
    return jsonb_build_object('status', 'invalid');
  end if;
  select email into v_email from auth.users where id = v_uid;
  select * into v_reg from crrah_registry where holder_code = p_code;

  if v_reg.contact_email is not null and v_email is not null then
    if lower(v_reg.contact_email) = lower(v_email)
       or split_part(lower(v_reg.contact_email), '@', 2) = split_part(lower(v_email), '@', 2)
    then
      v_status := 'approved';
    end if;
  end if;

  insert into user_holders (user_id, holder_code, status, granted_by)
  values (v_uid, p_code, v_status,
          case when v_status = 'approved' then 'registry-match' else null end)
  on conflict (user_id, holder_code) do update
    set status = greatest(user_holders.status, excluded.status);  -- approved > pending lexically

  if v_status = 'pending' and v_reg.contact_email is not null then
    insert into holder_verifications (user_id, holder_code)
    values (v_uid, p_code) returning token into v_token;
    return jsonb_build_object('status', 'pending', 'token', v_token,
                              'registered_email', v_reg.contact_email);
  end if;
  return jsonb_build_object('status', v_status);
end $$;
revoke all on function claim_holder(text) from public;
grant execute on function claim_holder(text) to authenticated;

create or replace function confirm_holder(p_token uuid)
returns text language plpgsql security definer set search_path = public as $$
declare v record;
begin
  select * into v from holder_verifications
   where token = p_token and used_at is null and expires_at > now();
  if v is null then return 'invalid-or-expired'; end if;
  update holder_verifications set used_at = now() where token = p_token;
  update user_holders set status = 'approved'
   where user_id = v.user_id and holder_code = v.holder_code;
  return 'approved';
end $$;
revoke all on function confirm_holder(uuid) from public;
grant execute on function confirm_holder(uuid) to anon, authenticated;

create or replace function my_claims()
returns table (holder_code text, status text)
language sql security definer set search_path = public as $$
  select holder_code, status from user_holders where user_id = auth.uid()
$$;
revoke all on function my_claims() from public;
grant execute on function my_claims() to authenticated;
