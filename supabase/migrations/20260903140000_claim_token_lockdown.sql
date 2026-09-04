-- Security fix (found in legal/security review): claim_holder returned the
-- verification token AND the unmasked registered email to ANY authenticated
-- caller. A user could invoke the RPC directly, skip /api/claim, and confirm
-- their own claim — making the emailed-consent gate decorative.
--
-- Fix: the token and registered email are released only to callers presenting
-- the server secret (held in app_secrets, readable by no role; the Next API
-- route passes it from env). Direct callers still create a pending claim but
-- learn nothing. Also fixes the status upsert: greatest() compares text, and
-- 'pending' > 'approved' alphabetically, so a re-claim DOWNGRADED an approved
-- claim; approved now sticks.
create table if not exists app_secrets (
  name text primary key,
  value text not null
);
revoke all on app_secrets from public, anon, authenticated;

create or replace function claim_holder(p_code text, p_server_secret text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_uid uuid := auth.uid();
  v_email text;
  v_reg record;
  v_status text := 'pending';
  v_token uuid;
  v_is_server boolean := false;
  v_freemail text[] := array['gmail.com','yahoo.com','outlook.com','hotmail.com',
                             'aol.com','icloud.com','proton.me','protonmail.com',
                             'msn.com','live.com','mail.com','gmx.com','yandex.com'];
  v_dom text;
begin
  if v_uid is null then raise exception 'not authenticated'; end if;
  p_code := upper(trim(p_code));
  if p_code !~ '^[A-Z0-9_]{3,12}$' then
    return jsonb_build_object('status', 'invalid');
  end if;

  select (p_server_secret is not null and p_server_secret = value) into v_is_server
  from app_secrets where name = 'claim_rpc';
  v_is_server := coalesce(v_is_server, false);

  select email into v_email from auth.users where id = v_uid;
  select * into v_reg from crrah_registry where holder_code = p_code;

  if v_reg.holder_code is null then
    return jsonb_build_object('status', 'unknown');
  end if;

  if v_reg.contact_email is not null and v_email is not null then
    v_dom := split_part(lower(v_reg.contact_email), '@', 2);
    if lower(v_reg.contact_email) = lower(v_email) then
      v_status := 'approved';
    elsif v_dom = split_part(lower(v_email), '@', 2)
          and not (v_dom = any(v_freemail)) then
      v_status := 'approved';
    end if;
  end if;

  insert into user_holders (user_id, holder_code, status, granted_by)
  values (v_uid, p_code, v_status,
          case when v_status = 'approved' then 'registry-match' else null end)
  on conflict (user_id, holder_code) do update
    set status = case when user_holders.status = 'approved'
                      then 'approved' else excluded.status end;

  if v_status = 'pending' and v_reg.contact_email is not null and v_is_server then
    insert into holder_verifications (user_id, holder_code)
    values (v_uid, p_code) returning token into v_token;
    return jsonb_build_object('status', 'pending', 'token', v_token,
                              'registered_email', v_reg.contact_email);
  end if;
  return jsonb_build_object('status', v_status);
end $$;
