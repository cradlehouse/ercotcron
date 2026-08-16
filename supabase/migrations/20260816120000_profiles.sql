-- Subscriber profiles: one row per auth user, created automatically on signup.
-- plan: 'trial' -> 'active' -> 'cancelled' (billing wiring comes later; the
-- trial clock starts at signup).

create table if not exists profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  email      text not null,
  plan       text not null default 'trial' check (plan in ('trial','active','cancelled','comp')),
  trial_ends date not null default (now()::date + 30),
  created_at timestamptz not null default now()
);

alter table profiles enable row level security;

drop policy if exists "own profile" on profiles;
create policy "own profile" on profiles
  for select using (auth.uid() = user_id);

create or replace function handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into profiles (user_id, email) values (new.id, new.email)
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();
