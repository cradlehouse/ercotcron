# Handoff — state, risks, next steps

Written 26 Jul 2026.

**Deployed:** dashboard is live at https://ercotcron.vercel.app (Vercel, green).
Supabase is linked to this repo, and the migrations have been applied to the
production database. **Not yet deployed:** the Render ingest service. No live
ERCOT call has ever been made.

## Verified

- **67 tests pass** (`.venv/bin/python -m pytest`, ~0.4s, no network). Covers
  DST conversion both directions, the repeat-hour flag, interval flooring,
  auth-token caching and refresh, rate limiting, retry/backoff, pagination, and
  the bitemporal insert/revision paths against a fake database.
- **Dashboard typechecks and builds clean** (`npx tsc --noEmit`, `npx next build`),
  including with no Supabase env vars set — which is how it will first deploy to
  Vercel. All three pages were loaded in a browser and render explanatory empty
  and error states rather than crashing.
- **Migrations applied to production.** All three live pages query Supabase and
  return zero rows with no error, which means every table and view resolves:
  `latest_prices`, `rt_spp`, `ingest_runs`, `feed_latency`, `rt_spp_gaps`,
  `revision_counts`, `spp_vs_lmp_5min`. A missing relation would surface as a
  PostgREST error on the page instead.

## Not verified — the real risks

**1. The schema exists, but its behaviour is unproven.** The relations are
there; what has never run is the logic inside them — `capture_price_revision`,
`ensure_month_partition`, `detach_partitions_before`. No row has ever been
inserted, so no partition has been routed and no revision has been captured.

**RLS is likewise unproven.** With RLS on and no policy, PostgREST returns an
empty array rather than an error — identical to an empty table. Since there is
no data, "policy permits the read" and "policy is missing" look exactly the
same from the dashboard. This only becomes testable once rows exist.

To close both: insert a price, update it, and confirm a `price_revisions` row
appears with the old value and that the dashboard can still read the table.

**2. The ERCOT endpoint paths and parameter names are unconfirmed.** They come
from the API docs, not from a successful response. Field names in particular are
guesses at ERCOT's casing (`deliveryDate` vs `DeliveryDate`), which is why
`ercot/ingest.py` reads through a `field()` helper that accepts several spellings
and why `empty` is a first-class run status. The first real run is the test.

`scripts/describe_endpoint.py` exists for exactly this: it makes one authorized
request and prints the response envelope and field names, so you can correct the
mapping before running a full ingest.

**3. Nothing has run against a real database.** The tests use a fake connection.
Constraint names, the ON CONFLICT targets, and the partition routing are all
unexercised against live Postgres.

## Deliberate choices worth knowing

- **`TRACKED_POINTS` defaults to hubs and load zones**, not every settlement
  point. Every node at 5-minute grain is ~105M rows/year. Widen deliberately.
- **The 5-minute LMP and RTD jobs are separate.** RTD is ERCOT's forward-looking
  indicative price and is *not* settled money; storing it in the same table as
  settled LMP would silently corrupt any backtest that assumed settlement.
- **The spring-forward skipped hour raises** rather than being coerced. Ingest
  catches it, logs, and skips the row. If ERCOT ever does send that hour, you
  want a loud log line, not a silent overwrite.
- **The dashboard shows "—" and "query failed"**, never a green zero, when a
  health query errors. On a monitoring page, "we could not tell" and "all clear"
  must not look alike.

## Suggested order from here

1. Get ERCOT credentials into `.env`; run `scripts/describe_endpoint.py` and fix
   the field mapping (risk 2).
2. Run one job by hand via `scripts/run_ingest.py`; check `ingest_runs` for `ok`
   rather than `empty`. This is also what proves the revision trigger, partition
   routing, and RLS policies (risk 1) — the first real rows exercise all three.
3. Deploy the ingest service to Render as a **Web Service, not a Cron Job** —
   the schedule lives inside the process. Not the free plan: free instances
   spin down when idle, which stops the scheduler.
4. Set the `HEARTBEAT_URL_*` variables. Without them, a job that silently stops
   returning rows will not tell anyone.

## Notes

`supabase/migrations/20260726120000_core.sql` creates the `pgcrypto` extension,
which nothing uses — ids are `bigserial`. It is a harmless no-op on Supabase,
where the extension already exists. It is left in place deliberately: that
migration has already been applied to production, and editing an applied
migration makes the file stop describing what actually ran. Drop the line only
as part of a new migration, if it ever matters.
