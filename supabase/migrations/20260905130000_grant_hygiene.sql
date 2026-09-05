-- Belt-and-suspenders from the security review (finding #3 generalized):
-- tables the web app never touches directly keep Supabase's default
-- full-CRUD grants to anon/authenticated. RLS default-deny hides them today,
-- but one careless `using (true)` policy later and they're world-readable —
-- the exact pattern that exposed path_valuations. Deny at the GRANT layer so
-- a future policy mistake exposes nothing.
--
-- Kept for web roles: tables with deliberate scoped policies (profiles,
-- user_holders, watchlists, credit_grants, alert_*, sheets) and the public
-- ERCOT mirrors. Everything below is pipeline/ops-only or definer-mediated.
revoke all on paper_bids from anon, authenticated;
revoke all on marks from anon, authenticated;
revoke all on mark_runs from anon, authenticated;
revoke all on access_log from anon, authenticated;
revoke all on market_intel from anon, authenticated;
revoke all on intel_impacts from anon, authenticated;
revoke all on path_valuations from anon, authenticated; -- close the non-SELECT residue too
revoke all on app_secrets from anon, authenticated;      -- already revoked; restated for the record
