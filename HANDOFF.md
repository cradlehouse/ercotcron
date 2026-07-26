# Handoff — state, risks, next steps

Written 26 Jul 2026.

**Running end to end.** Ingest is live on Render, the dashboard is live at
https://ercotcron.vercel.app, and real ERCOT prices are flowing. All four feeds
have completed successful runs against the production database.

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

**1. ~~The schema exists, but its behaviour is unproven.~~ MOSTLY CLOSED.**
Partition routing and RLS are both proven — rows are landing in the monthly
partitions, and the dashboard renders real prices through the anon key, which
an empty table could never have demonstrated.

Still unproven: **`capture_price_revision`**. ERCOT has not restated a price
since ingest began, so no revision has been captured. Confirmed only when
`rows_revised` goes above zero on a run, or by hand — update a stored price and
check `price_revisions` holds the old value.

The failure that got here is worth remembering: the upsert detected
insert-vs-update with `returning (xmax = 0)`, which Postgres refuses on
partitioned tables. The test suite uses a fake connection, so it passed for
weeks. Only live Postgres could catch it — see the "unexercised against live
Postgres" warning that used to be in this section.

**2. ~~The ERCOT endpoint paths and parameter names are unconfirmed.~~ CLOSED.**
Verified against the live API on 26 Jul 2026:

- All four endpoint paths confirmed from ERCOT's own product catalog
  (`GET /api/public-reports` lists every product and its data endpoint).
- All field names the code reads are correct.
- All query parameters are honoured — checked via `_meta.query.parameterCount`,
  which is the only way to tell an accepted filter from a silently ignored one.
  A wrong parameter name is not an error; it returns unfiltered data.

Two absences, both harmless because the columns are nullable: no endpoint
returns a `postDatetime`, so `posted_at` is always null; and `np6-788-cd`
returns only `LMP`, so the energy/congestion/loss component columns stay null.

Fixed in the process: both Azure B2C auth constants were wrong (the policy name
and the client id), so every request 404'd at the token step.

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

## Backfill: measured volumes

Only the live feeds run today; no history has been loaded. Measured 26 Jul 2026,
one day, **all** settlement points:

| feed | rows/day | 2 years, unfiltered |
| --- | --- | --- |
| dam | 24,816 | 18.1M |
| rtm (15-min) | 100,416 | 73.3M |
| lmp5 (5-min) | 298,826 | 218M |
| rtd | 3,275,712 | **2.4 billion** |

**Filter server-side when backfilling.** `settlementPoint=HB_HUBAVG` returns 96
rows/day on rtm and 289 on lmp5, against 100k and 299k unfiltered — roughly
1,000× less per point. Two years of 5-minute data for the tracked points is then
~3.2M rows in ~650 requests, about half an hour, rather than thirty hours.

**Do not apply that to the live jobs.** For a 20-minute window, unfiltered is a
single request; per-point filtering would be fifteen. Unfiltered wins live,
filtered wins for backfill — opposite regimes.

**Never backfill rtd wholesale.** It stores every forecast vintage, hence 3.3M
rows a day. Scope it to specific points and a short window.

Retention is not pinned down: 2025-01-01 returns data, 2019-01-01 returns none.
The probes that would have bracketed it hit HTTP 429 — the rate limit is real,
so backfill must go through the client's pacing, not an ad-hoc script.

## Notes

**Deploys briefly double-run every job.** Render starts the new container before
draining the old, so two schedulers overlap for a few seconds and both fire.
Harmless — the primary keys make it idempotent — but it doubles the ERCOT
request rate during the handover, which is enough to draw a 429.

`supabase/migrations/20260726120000_core.sql` creates the `pgcrypto` extension,
which nothing uses — ids are `bigserial`. It is a harmless no-op on Supabase,
where the extension already exists. It is left in place deliberately: that
migration has already been applied to production, and editing an applied
migration makes the file stop describing what actually ran. Drop the line only
as part of a new migration, if it ever matters.
