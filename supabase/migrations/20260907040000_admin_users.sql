-- Admin screen: who's actually here. One admin-gated read over auth.users
-- joined to profiles / claimed holder codes / terms acceptances, so the
-- user list lives on /app/admin and the method page stays pure method.
create or replace function get_admin_users()
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'users', coalesce((
      select jsonb_agg(jsonb_build_object(
               'email', u.email,
               'created', u.created_at,
               'confirmed', u.email_confirmed_at is not null,
               'last_sign_in', u.last_sign_in_at,
               'plan', p.plan,
               'role', p.role,
               'trial_ends', p.trial_ends,
               'holders', h.codes,
               'terms', t.accepted_at)
             order by u.last_sign_in_at desc nulls last, u.created_at desc)
        from auth.users u
        left join profiles p on p.user_id = u.id
        left join lateral (
          select array_agg(holder_code order by holder_code) as codes
            from user_holders where user_id = u.id
        ) h on true
        left join lateral (
          select max(accepted_at) as accepted_at
            from terms_acceptances where user_id = u.id
        ) t on true), '[]'::jsonb))
  where exists (select 1 from profiles
                 where user_id = auth.uid() and role = 'admin');
$$;
revoke execute on function get_admin_users() from public, anon;
grant execute on function get_admin_users() to authenticated;
