# ercotcron

Scheduled ingestion of ERCOT wholesale electricity prices into Postgres, with a
read-only monitoring dashboard.

Three feeds, three cadences:

| feed | table | grain | schedule (America/Chicago) |
| --- | --- | --- | --- |
| Day-Ahead Market SPP | `dam_spp` | hourly | 12:45, then hourly retries until it lands |
| Real-Time Market SPP | `rt_spp` | 15-minute | every 15 minutes, at :05 past |
| Real-Time LMP | `rt_lmp_5min` | 5-minute | every 5 minutes |
| RTD indicative LMP | `rtd_lmp` | 5-minute forecast | every 5 minutes |

## Why the pieces are shaped this way

**One long-lived Render service, not six cron jobs.** A single process is what
makes the shared bearer token, the shared rate limiter, and APScheduler's
overlap protection possible. Six cron containers would each cold-start and
re-authenticate every tick — roughly 288 needless token requests a day from the
5-minute job alone — and Render's cron scheduler is UTC-only, which would drift
the day-ahead job by an hour at every DST transition. Schedules live in
`ercot/jobs.py`, pinned to `America/Chicago`.

**Prices are bitemporal.** ERCOT restates prices after the fact. Every table
carries `interval_start` (when the power flowed) alongside `ingested_at` and
`posted_at` (when we learned the price). A restatement updates the current row
and writes the old value to `price_revisions`, so a backtest can ask what was
known at a past moment rather than what is known now — the difference between a
strategy that would have worked and one that only appears to.

**DST is handled explicitly, not by luck.** ERCOT operating days are 23, 24, or
25 hours. `ercot/timeutil.py` converts Central wall-clock to absolute UTC
instants, using ERCOT's repeat-hour flag to disambiguate the duplicated 01:00
hour each autumn. The hour skipped each spring raises rather than silently
mapping onto the following hour's instant, which would collide on the primary
key and overwrite real prices. Every stored timestamp is UTC; only the display
layer is Central.

**Empty is a distinct run status.** A request that succeeds and returns zero
rows is the signature of a wrong query-parameter name, and it looks exactly like
a quiet market. `ingest_runs` records `empty` separately from `ok` and `error`
so the health page can surface it.

## Layout

```
ercot/          ingest package — client, config, timeutil, ingest, jobs, service
supabase/       SQL migrations (schema, partitions, views, RLS)
scripts/        one-off CLI entry points (manual run, backfill, endpoint probe)
tests/          pytest suite, no network
app/ lib/       Next.js dashboard (read-only, anon key, RLS)
```

## Local setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and fill it in. Then apply the migrations to your
Supabase project (SQL editor, or `supabase db push`), oldest first.

Run one ingest by hand — this is the fastest way to prove credentials and
endpoint parameters are right:

```bash
.venv/bin/python scripts/run_ingest.py dam
```

Tests (no network, no database):

```bash
.venv/bin/python -m pytest
```

Dashboard:

```bash
npm install && npm run dev
```

## Deploying

**Ingest → Render.** `render.yaml` defines the service. Create the `ercot-secrets`
env group with `ERCOT_USERNAME`, `ERCOT_PASSWORD`, `ERCOT_SUBSCRIPTION_KEY`,
`DATABASE_URL`, and optionally `TRACKED_POINTS` and `HEARTBEAT_URL_*`.
`DATABASE_URL` should be the Supabase **transaction pooler** string (port 6543).

**Dashboard → Vercel.** Needs only `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY`. It reads through RLS and must never be given
the service-role key or `DATABASE_URL`. Do not add a Vercel cron — that would
double every ERCOT pull.

`vercel.json` pins the install and build commands, and `.vercelignore` keeps the
Python files out of the upload. Both are load-bearing: this repo holds a Python
service and a Node dashboard side by side, and a bare `requirements.txt` at the
root makes Vercel detect a Python project and run `uv pip install` before the
Next.js build — which fails on any Python version lacking `psycopg-binary`
wheels. Removing either file brings that back.

## Operating

`GET /health` reports scheduler state and the last run per job. `GET /runs`
returns recent run history. `POST /trigger/{job}` forces a run and requires the
`TRIGGER_SECRET` bearer token, because it spends ERCOT rate-limit budget.

The dashboard's **health** page is the one to check: failed runs, empty runs,
missing 15-minute intervals, publication lag, and revision counts. Gaps are
repaired by re-running the relevant job over a wider window:

```bash
.venv/bin/python scripts/run_ingest.py lmp5 --since-minutes 720
```

## Rate limits

The ERCOT public API allows 30 requests/minute; the client's shared limiter is
set to 24 to leave headroom for retries. `TRACKED_POINTS` defaults to hubs and
load zones — storing every settlement point is roughly 105M five-minute rows a
year, well past what a small Postgres instance is sized for.

Never fail over to the secondary subscription key at runtime: both keys share
one quota and one suspension status, so a fallback burns the spare without
buying availability. The secondary exists for zero-downtime rotation.
