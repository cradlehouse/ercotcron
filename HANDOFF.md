# Handoff — state, risks, next steps

Written 26 Jul 2026. Nothing is deployed and no live ERCOT call has ever been
made.

## Verified

- **67 tests pass** (`.venv/bin/python -m pytest`, ~0.4s, no network). Covers
  DST conversion both directions, the repeat-hour flag, interval flooring,
  auth-token caching and refresh, rate limiting, retry/backoff, pagination, and
  the bitemporal insert/revision paths against a fake database.
- **Dashboard typechecks and builds clean** (`npx tsc --noEmit`, `npx next build`),
  including with no Supabase env vars set — which is how it will first deploy to
  Vercel. All three pages were loaded in a browser and render explanatory empty
  and error states rather than crashing.
- **Migrations parse** under the real PostgreSQL parser (`pglast`), 47
  statements across 4 files.

## Not verified — the real risks

**1. The migrations have never been executed.** Parsing is not applying. Nothing
has confirmed that the tables, monthly partitions, revision trigger, views, and
RLS policies actually work together. The PL/pgSQL bodies —
`capture_price_revision`, `ensure_month_partition`, `detach_partitions_before` —
are opaque strings to a parser, so their logic is entirely unproven. This is the
largest open risk.

(I tried validating the PL/pgSQL with `pglast.parse_plpgsql`, but that function
is broken in v8.4 — it fails a trivially valid `begin return new; end` body with
a JSON decode error, so it proves nothing either way. Don't trust a green result
from it.)

To close this: apply the four files in order to a scratch Supabase project, then
insert a row, update its price, and confirm a `price_revisions` row appears with
the old value.

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

1. Create the Supabase project; apply migrations; confirm the revision trigger
   fires (risk 1).
2. Get ERCOT credentials into `.env`; run `scripts/describe_endpoint.py` and fix
   the field mapping (risk 2).
3. Run each job once by hand via `scripts/run_ingest.py`; check `ingest_runs`
   for `ok` rather than `empty`.
4. Deploy to Render, point the dashboard at Supabase, deploy to Vercel.
5. Set the `HEARTBEAT_URL_*` variables. Without them, a job that silently stops
   returning rows will not tell anyone.
