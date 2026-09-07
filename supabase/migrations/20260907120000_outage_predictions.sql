-- Outage predictions, pre-registered. Each row is a falsifiable claim made
-- BEFORE the event: unit, expected window, the basis, and the node map it
-- will be graded against (outage_node_deltas at made_on). Append-only like
-- the sheets — identity immutable, only grading columns mutable — so when
-- the outage happens (or doesn't) the claim is scored as written.
create table if not exists outage_predictions (
  id bigint generated always as identity primary key,
  made_on date not null default current_date,
  unit_code text not null,
  window_start date not null,
  window_end date not null,
  confidence text not null,          -- validated / clock-only / single-episode
  basis text not null,
  status text not null default 'open',   -- open / hit / missed / graded
  graded_at timestamptz,
  outcome text
);
alter table outage_predictions enable row level security;
revoke all on outage_predictions from anon, authenticated;

create or replace function outage_predictions_guard() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'outage_predictions is append-only';
  end if;
  if new.unit_code <> old.unit_code or new.made_on <> old.made_on
     or new.window_start <> old.window_start or new.window_end <> old.window_end
     or new.confidence <> old.confidence or new.basis <> old.basis then
    raise exception 'outage_predictions: the claim is immutable; only grading may change';
  end if;
  return new;
end $$;
drop trigger if exists outage_predictions_guard on outage_predictions;
create trigger outage_predictions_guard
  before update or delete on outage_predictions
  for each row execute function outage_predictions_guard();

insert into outage_predictions (unit_code, window_start, window_end, confidence, basis) values
 ('CPSES_UNIT1', '2026-10-01', '2026-11-30', 'clock + single-episode map',
  '18-month refuel cycle (Oct 2023 -> Apr 2025 -> due now). Nuclear class validated out-of-sample on STP G1/G2 (17-21/25 held-out sign agreement); this unit''s own node map is from one episode (Apr 2025).'),
 ('MLSES_UNIT2', '2026-11-01', '2027-02-28', 'validated',
  'Annual winter maintenance (Nov 24, Jan 25, Dec 25, Jan 26). Node map scored 22-24/25 on its held-out Feb 2026 outage.'),
 ('STP_STP_G2', '2027-03-01', '2027-05-31', 'validated (clock)',
  '18-month refuel cycle (Oct 22 -> Mar 24 -> Oct 25 -> due spring 27). Map scored 21/25 held out.'),
 ('STP_STP_G1', '2027-09-01', '2027-11-30', 'validated (clock)',
  '18-month refuel cycle (Oct 24 -> Mar 26 -> due fall 27). Map scored 20/24 held out.'),
 ('OGSES_UNIT2', '2027-01-01', '2027-04-30', 'validated (cool season only)',
  'Cool-season maintenance recurs annually; season-matched map scored 18/25 held out. Summer signal is noise; this claim is cool-season only.');
