-- Append-only book of things that looked tradeable and were not, and data that
-- looked usable and was not. The point is to stop relearning the same bad
-- trade every season. Rows are never updated or deleted — supersede with a new
-- row that references the old id if a lesson is later revised.
create table if not exists negative_knowledge (
  id          bigserial primary key,
  learned_on  date not null,
  category    text not null,   -- trap | data_quality | dead_end | method
  subject     text not null,   -- the path/constraint/dataset/rule concerned
  lesson      text not null,   -- one sentence: what burned us
  evidence    text,            -- the number or test that proved it
  supersedes  bigint references negative_knowledge(id),
  created_at  timestamptz not null default now()
);
alter table negative_knowledge enable row level security;
drop policy if exists negative_knowledge_read on negative_knowledge;
create policy negative_knowledge_read on negative_knowledge for select using (true);
grant select on negative_knowledge to anon, authenticated;
