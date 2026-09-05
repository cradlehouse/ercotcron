-- Legal review A9 (machinery half): clickwrap needs STORED acceptance
-- evidence. Append-only record of who accepted which terms version when;
-- the agree gate in the member area writes through accept_terms() with a
-- live session, so every row is tied to an authenticated user.
create table if not exists terms_acceptances (
  id bigint generated always as identity primary key,
  user_id uuid not null,
  terms_version text not null,
  accepted_at timestamptz not null default now(),
  user_agent text
);
alter table terms_acceptances enable row level security;
revoke all on terms_acceptances from anon, authenticated;

create or replace function terms_acceptances_guard() returns trigger
language plpgsql as $$
begin
  raise exception 'terms_acceptances is append-only';
end $$;
drop trigger if exists terms_acceptances_guard on terms_acceptances;
create trigger terms_acceptances_guard
  before update or delete on terms_acceptances
  for each row execute function terms_acceptances_guard();

create or replace function accept_terms(p_version text, p_user_agent text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  insert into terms_acceptances (user_id, terms_version, user_agent)
  values (auth.uid(), p_version, left(coalesce(p_user_agent, ''), 400));
end $$;

create or replace function my_terms_acceptance(p_version text)
returns boolean language sql security definer set search_path = public as $$
  select exists (select 1 from terms_acceptances
                  where user_id = auth.uid() and terms_version = p_version);
$$;

revoke execute on function accept_terms(text, text) from public, anon;
revoke execute on function my_terms_acceptance(text) from public, anon;
grant execute on function accept_terms(text, text) to authenticated;
grant execute on function my_terms_acceptance(text) to authenticated;
