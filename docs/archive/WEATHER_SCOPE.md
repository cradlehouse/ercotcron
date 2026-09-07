# Scope: wind, solar and load forecasts → net load → price

Not built. This is the plan, with every field name verified against the live
API on 26 Jul 2026.

## Why this is the prediction layer

ERCOT price is set by the marginal generator. What decides which generator that
is, hour by hour, is **net load**:

```
net load = load − wind − solar
```

High wind against low load pushes cheap generation to the front of the stack and
prices go negative. Low wind against high load reaches for gas peakers and
prices spike. Everything else — congestion, outages, reserve scarcity — moves
prices around that spine.

The edge is a timing one. **The day-ahead market closes at 10:00 CT for the next
operating day**, and ERCOT publishes wind and load forecasts seven days out. So
tomorrow's West Texas wind ramp is visible before DAM bidding closes. That gap
between "forecast published" and "market closed" is the whole opportunity, and
it needs no weather vendor: ERCOT's own forecasts are what the market prices
against.

## Endpoints (verified)

| purpose | EMIL | path | cadence |
| --- | --- | --- | --- |
| wind actual + forecast by region | NP4-742-CD | `/np4-742-cd/wpp_hrly_actual_fcast_geo` | hourly |
| solar actual + forecast by region | NP4-745-CD | `/np4-745-cd/spp_hrly_actual_fcast_geo` | hourly |
| 7-day load forecast by weather zone | NP3-561-CD | `/np3-561-cd/7d_load_fcast_by_wzn` | hourly |
| intra-hour wind forecast by region | NP4-751-CD | — | 5 min |
| intra-hour load forecast by weather zone | NP3-562-CD | — | 5 min |

Start with the three hourly ones. The 5-minute intra-hour forecasts are a second
phase: they sharpen dispatch timing but do not change the day-ahead thesis.

### Wind response shape — 29 fields, wide not long

Metrics `gen`, `COPHSL`, `STWPF`, `WGRPP` × regions `SystemWide`, `Panhandle`,
`Coastal`, `South`, `West`, `North`, plus `HSLSystemWide`, `postedDatetime`,
`deliveryDate`, `hourEnding`, `DSTFlag`.

- `gen` — actual generation. **Null for future hours**, which is how you tell a
  forecast row from a settled one.
- `STWPF` — Short-Term Wind Power Forecast. The headline number.
- `WGRPP` — probabilistic (80th percentile) forecast. The pair `STWPF`/`WGRPP`
  gives a forecast *spread*, and the spread is itself signal: a wide gap means
  ERCOT is unsure, and uncertain wind is when prices move most.
- `COPHSL` — what generators themselves reported as available.

### Load response shape

`coast`, `east`, `farWest`, `north`, `northCentral`, `southCentral`, `southern`,
`west`, `systemTotal`, plus `postedDatetime`, `deliveryDate`, `hourEnding`
(VARCHAR `"1:00"`, unlike wind's INTEGER), `DSTFlag`.

**Weather zones are not load zones.** `farWest` here is not `LZ_WEST` in the
price tables — different geographies for different purposes. Any join between
them is an approximation and must be labelled as one on the screen.

## Schema

Store **long, not wide**. The API returns one row per hour with 24 region
columns; a `(delivery_date, hour_ending, region, metric, mw)` shape means adding
a region later is data, not a migration. Each feed keeps its own table because
their grains and region vocabularies differ.

```sql
create table wind_forecast (
  interval_start timestamptz not null,   -- UTC, from delivery_date + hour_ending
  delivery_date  date        not null,   -- ERCOT operating day
  hour_ending    smallint    not null,
  region         text        not null,   -- SystemWide, Panhandle, Coastal, South, West, North
  actual_mw      numeric(12,2),          -- null until the hour settles
  forecast_mw    numeric(12,2),          -- STWPF
  forecast_p80_mw numeric(12,2),         -- WGRPP
  cop_hsl_mw     numeric(12,2),
  posted_at      timestamptz,
  ingested_at    timestamptz not null default now(),
  primary key (interval_start, region)
);
```

`solar_forecast` mirrors it. `load_forecast` is the same shape with `zone` and a
single `forecast_mw`.

**Forecast vintages are the open design question.** A primary key of
`(interval_start, region)` keeps only the newest forecast for an hour. That is
right for "what do we expect now" and wrong for "how did the forecast for
Thursday 5pm evolve across the week" — which is the more valuable question, and
the one that makes forecast *revisions* tradeable. Adding `posted_at` to the key
keeps every vintage at roughly 7× the rows (a 7-day-ahead hour gets re-forecast
hourly). Storage is trivial at these volumes; the reason to hesitate is that the
"current forecast" query then needs a `distinct on`, exactly like
`rt_spp_asof`. **Recommendation: key on `(interval_start, region, posted_at)`
and add a `latest_wind_forecast` view.** It matches the bitemporal design
already in place, and the vintage history cannot be recovered later if skipped.

## Ingest

Three jobs in `ercot/jobs.py`, hourly at :20 past (forecasts post near the top of
the hour; :20 avoids racing publication):

- `wind` — 8 days back-to-forward, one request
- `solar` — same
- `load_fcast` — same

Volume is negligible: 6 regions × 24 hours × 8 days ≈ 1,150 rows per wind run.
No paging concerns, no rate-limit pressure. These are cheap next to the price
feeds.

Two parsing notes that will bite otherwise:

1. Wind `hourEnding` is an INTEGER; load `hourEnding` is a VARCHAR `"1:00"`.
   `_hour_ending()` already handles both — do not add a second parser.
2. Rows for future hours have `gen` null. That is the normal case, not a
   validation failure; do not skip those rows.

## Screen: `/forecast`

One page, three stacked sections, reading top to bottom as an argument.

**1. Net load, next 7 days.** The headline chart. A stacked area of forecast
wind + solar under a load line, with the gap between them shaded as net load —
because the gap *is* the price. Overlay DAM price where it exists (today and
tomorrow), so the correlation is visible rather than asserted. A vertical marker
at the next 10:00 CT DAM close, labelled, so the actionable window is a thing
you can see rather than something you have to remember.

**2. Regional wind ramps.** Small multiples, one per region, forecast MW over
the next 48 hours. Ramps are what matter — a 3,000 MW Panhandle swing between
2pm and 6pm is a price event. Highlight the steepest 4-hour deltas rather than
absolute levels, since absolute level is mostly nameplate capacity.

**3. Forecast skill.** Scatter or binned bias of forecast vs actual by lead
time, from the rows where `gen` is now populated. This is the section that keeps
the page honest: it says how much the forecast above is worth. If ERCOT's
day-ahead wind forecast has a 15% MAE, the net-load chart deserves proportionate
scepticism, and the user should see that without having to know it independently.

Reuse the existing `PriceCurve` crosshair pattern for the ramp charts.

## What this does not do

It does not predict price. It shows the input the market prices against, and
scores how reliable that input has been. A regression from net load to price is
a further step and should not be presented as forecasting until it has been
backtested with `rt_spp_asof` — using current data to backtest would answer
"what is knowable now", not "what was knowable then", and that is precisely the
mistake the bitemporal schema exists to prevent.

## Estimate

Schema + three ingest jobs + tests: about half the work. The `/forecast` screen
is the other half, and the net-load chart is most of that. Field names are
confirmed, so the unknowns are behavioural — mainly how ERCOT revises forecasts
through the day, which only becomes visible once vintages accumulate.
