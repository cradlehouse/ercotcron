# ercotcron — Shadowprice

Scheduled ingestion of ERCOT wholesale prices, constraints, CRR auction
results, and fundamentals into Postgres — plus the Next.js site that turns
them into CRR bid sheets, marks, and a public track record.

Four pieces:

- **Ingest** — one long-lived Python service on Render (`ercot/service.py`,
  APScheduler), running the 17 jobs below on Chicago-local schedules.
- **Database** — Supabase Postgres. 67 migrations, RLS on everything, and
  security-definer RPCs for anything a browser is allowed to ask for.
- **Site** — Next.js 15.5 on Vercel. Public product pages, member pages behind
  Supabase auth, ops pages behind basic auth. Reads only through the anon key
  and RLS; it never holds `DATABASE_URL` or the service-role key.
- **Research** — `strategy/` CLIs (backtests, path discovery, marks, auction
  prep). Currently laptop-run against the same database, not deployed.

## Scheduled jobs

All times America/Chicago (see below for why). Defined in `ercot/jobs.py`.

| job | cadence | what it ingests / does |
| --- | --- | --- |
| `lmp5` | every 5 min | 5-minute SCED LMP, last 20 minutes |
| `rtd` | every 5 min, :02 offset | RTD indicative forecast vintages, last 15 minutes |
| `constraints` | every 10 min, :06 offset | binding transmission constraints and shadow prices, 60-minute lookback |
| `rtm` | :04 :19 :34 :49 | settled 15-minute SPP, current operating day |
| `lmp5_catchup` | hourly at :08 | 5-minute repair pass over the last 3 hours |
| `wind` | hourly at :20 | regional wind actual + forecast, 8-day window |
| `solar` | hourly at :24 | regional solar actual + forecast, 8-day window |
| `load_fcast` | hourly at :28 | seven-day load forecast by weather zone |
| `signals` | hourly at :34 | rebuild the scanner's materialised views |
| `weather` | hourly at :42 | independent wind forecasts (ECMWF/GFS/ICON) via Open-Meteo |
| `dam` | 11:47, 18:47 | day-ahead SPP, today and tomorrow |
| `partitions` | daily 03:10 | create monthly partitions three months ahead |
| `products` | daily 04:15 | rebuild the `node_graph` + `grid_geo` artifacts the site serves |
| `crr` | daily 08:40 | CRR monthly auction results, newest 2 auctions |
| `crr_lt` | daily 08:50 | CRR long-term auction results, newest 2 |
| `paper_score` | daily 09:05 | score open paper-trade batches against posted results |
| `points` | Mon 09:00 | settlement point catalogue refresh |

## Why the pieces are shaped this way

**One long-lived Render service, not seventeen cron jobs.** A single process is
what makes the shared bearer token, the shared rate limiter, and APScheduler's
overlap protection possible. Separate cron containers would each cold-start and
re-authenticate every tick — roughly 288 needless token requests a day from the
5-minute job alone — and Render's cron scheduler is UTC-only, which would drift
every wall-clock job by an hour at each DST transition. Schedules live in
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
so the health page can surface it. (The `constraints` job is the deliberate
exception: constraints only exist while something is congested, so it uses a
60-minute lookback to keep legitimate quiet spells from training you to ignore
`empty`.)

**The valuations stay locked in the database.** `path_valuations` and the other
product tables are readable only through security-definer RPCs with their own
gating; the anon key alone gets nothing. RLS is on every table, and member
pages fetch through RPCs scoped server-side to the caller (for example
`get_my_book()` returns only the signed-in holder's approved claims).

## Site routes

Public product pages:

| route | what it is |
| --- | --- |
| `/` | landing |
| `/map` | node relationship map — circle-pack of settlement points, from the nightly `node_graph` artifact |
| `/bids` | the auction order ticket — what to bid, at what price, how many MW, by when |
| `/bids/strip` | 2028 strip sheet for the Jul–Dec 2028 long-term auction |
| `/paths` | path spreads — the payoff side of a CRR |
| `/path` | one source→sink path in detail |
| `/methodology` | the published mark methodology |
| `/privacy`, `/terms` | policies |
| `/signin`, `/signup`, `/reset` | Supabase auth |

Member pages (Supabase auth):

| route | what it is |
| --- | --- |
| `/app` | member home — trial status + the products |
| `/app/book` | the signed-in holder's live positions, graded our way |
| `/app/method` | the method judged one sheet at a time — won / outbid / refused, with money |
| `/app/record` | the model's book — every paper batch put on record before auction results, and what happened |
| `/app/admin` | operator's desk — who's here, what they've claimed |

Ops pages (basic auth via `DASH_PASSWORD` in `middleware.ts`; reachable by URL,
not in the nav — and the gate **denies** when no password is configured, it
never fails open):

| route | what it is |
| --- | --- |
| `/health` | did the crons run, did they return anything, what changed |
| `/monitor` | latest price per point, interactive curve, range presets |
| `/scanner` | z-scored spreads, persistence, tails, what the auction charges for uncertainty |
| `/spikes` | what the 15-minute settled average concealed |
| `/trades` | the three trades this data supports, each with its live scoreboard |
| `/why` | why prices did what they did, and where that is repeatable enough to trade |

Any route not on the public or ops lists 404s at the middleware rather than
prompting for a password.

API routes: `/api/artifact` (serves the nightly-built map/graph artifacts),
`/api/claim` and `/api/verify-holder` (holder claim flow), `/api/unsubscribe`
(outreach email opt-out). The claim and unsubscribe routes present
`CLAIM_RPC_SECRET` to their RPCs server-side.

## Layout

```
ercot/          ingest package — client, config, timeutil, ingest, fundamentals,
                crr, weather, products, jobs, service
supabase/       SQL migrations (schema, partitions, views, RLS, RPCs)
scripts/        one-off CLI entry points (manual run, backfills, endpoint probe,
                sheet rendering, catalogue loads)
strategy/       research CLIs — backtest, discover_paths, marks, auction_prep,
                market_scan, strip_scan, ptdf, walk-forward (laptop-run)
tests/          pytest suite, no network
app/ lib/       Next.js site (anon key + RLS + RPCs only)
docs/           strategy, methodology, legal; docs/archive/ holds superseded docs
```

## Environment variables

From `.env.example` (names only — see the file for the full commentary):

| variable | purpose |
| --- | --- |
| `ERCOT_USERNAME` / `ERCOT_PASSWORD` | apiexplorer.ercot.com portal login; the token flow authenticates as you |
| `ERCOT_SUBSCRIPTION_KEY` | primary Public API key — never fail over to the secondary at runtime |
| `DATABASE_URL` | Supabase transaction-pooler string (port 6543); ingest only, bypasses RLS |
| `TRIGGER_SECRET` | guards `POST /trigger/{job}`, which spends rate-limit budget |
| `TRACKED_POINTS` | settlement points to store (default: hubs and load zones) |
| `HEARTBEAT_URL_*` | optional per-job heartbeat URLs (healthchecks.io or similar) |
| `SCHEDULER_ENABLED` | set false to run the API without the scheduler |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | optional raw CRR auction-zip archival to a private Storage bucket; service key, never near a browser |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the only two variables the Vercel site needs |
| `DASH_PASSWORD` | basic auth for the ops pages |
| `CLAIM_RPC_SECRET` | server secret the claim + unsubscribe API routes present to their RPCs |
| `RESEND_API_KEY` | claim-verification and outreach email; optional, claims fall back to manual review |
| `OUTREACH_POSTAL_ADDRESS` | CAN-SPAM postal address for outreach footers; env only, never rendered on the site |

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

Tests (83 passing, no network, no database):

```bash
.venv/bin/python -m pytest tests/
```

Site:

```bash
npm install && npm run dev
```

## Deploying

**Ingest → Render.** `render.yaml` defines the service. Create the `ercot-secrets`
env group with `ERCOT_USERNAME`, `ERCOT_PASSWORD`, `ERCOT_SUBSCRIPTION_KEY`,
`DATABASE_URL`, and optionally `TRACKED_POINTS` and `HEARTBEAT_URL_*`.
`DATABASE_URL` should be the Supabase **transaction pooler** string (port 6543).

**Site → Vercel.** Needs only `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (plus `DASH_PASSWORD` and `CLAIM_RPC_SECRET`
for the ops pages and claim flow). It reads through RLS and must never be given
the service-role key or `DATABASE_URL`. Do not add a Vercel cron — that would
double every ERCOT pull.

`vercel.json` pins the install and build commands, and `.vercelignore` keeps the
Python files out of the upload. Both are load-bearing: this repo holds a Python
service and a Node site side by side, and a bare `requirements.txt` at the
root makes Vercel detect a Python project and run `uv pip install` before the
Next.js build — which fails on any Python version lacking `psycopg-binary`
wheels. Removing either file brings that back.

## Operating

`GET /health` on the Render service reports scheduler state and the last run
per job. `GET /runs` returns recent run history. `POST /trigger/{job}` forces a
run and is guarded because it spends ERCOT rate-limit budget — it takes the
secret in an `X-Trigger-Secret` header, not as a bearer token:

```bash
curl -X POST -H "X-Trigger-Secret: $TRIGGER_SECRET" \
  https://YOUR-SERVICE.onrender.com/trigger/dam
```

Job names are the ones in the table above.

The site's **/health** page is the one to check: failed runs, empty runs,
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
