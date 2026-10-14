# Pre-registration: the January 2027 weather outlook

**Registered:** 14 Oct 2026, before any base rate below was computed. The
git commit carrying this file and `strategy/winter_outlook.py` is the
timestamp. **Freeze:** Friday 4 Dec 2026, inputs cut off 3 Dec 23:59 CT,
before the JAN 2027 bid window (Dec 8–10). **Scored:** on or after 10 Feb
2027, once ERA5 covers all of January.

This is a physical outlook. It sits next to the January bid ticket and never
changes it. It holds no bid limit, mark or dollar adjustment. The valuation
and published-sheet logic is untouched.

## Why these questions

January 2026's payout was event-driven. Winter Storm Fern (Jan 25–28)
produced about half of that month's market-wide payout on positively priced
obligation CRRs. Jan 21–28 produced about 63%. Counterflow obligations lost
about $22M market-wide (read-only analysis, UI-review session, 14 Oct). So
the useful question is whether there will be cold-air outbreaks and wind
lulls, and when. The monthly average temperature matters less.

Our price history starts July 2024 and contains no El Niño winter. This
outlook therefore makes **no priced claim**. Our `load_forecast` and
`net_load` tables start April 2026 and hold no winter at all, so load
isn't modelled.

## Data (pinned)

- **Temperature:** ERA5 daily mean/min, from Open-Meteo's archive with
  `models=era5`, for Januaries 1991–2026. Each city's own ERA5 grid cell.
  The proxy is a fixed demand weighting, DFW 0.35, Houston 0.35, Austin
  0.15, San Antonio 0.15. It isn't validated and isn't ERCOT weather zones.
- **Wind:** ERA5 hourly 100 m wind at the 13 collector sites in
  `ercot/weather.py`. The generic `wind_power_fraction` curve is applied
  per site-hour first, then sites are averaged with equal weights.
- **ENSO:** CPC ONI v5, DJF value for each January.
- **Proxy check:** our `wind_power` SystemWide actuals, Dec–Feb 2024-25 and
  2025-26.
- **CPC context:** the latest ENSO discussion (12 Nov) and seasonal outlook
  (19 Nov) at freeze, transcribed with URL and issue date. They're context
  only. There is no calibrated conversion, so they don't move a probability.
  Later releases (10 Dec ENSO, 17 Dec January outlook) are excluded.

## Events (January 2027, CT calendar days)

| Id | Event | Definition |
|---|---|---|
| E1 | Freeze day | proxy daily mean ≤ 32°F; also counted |
| E2 | Severe cold | any day with proxy daily min ≤ 20°F |
| E3 | Outbreak run | ≥ 3 consecutive E1 days |
| W1 | Wind lull | ≥ 3 consecutive days with proxy wind capacity factor < 0.15 |
| T1 | Late timing | given any E1, the first falls on Jan 16–31 (secondary) |

Solar isn't an event. January solar is small, and the stress hours are
around sunrise and after dark.

## Forecasts

- **F0, climatology:** Januaries 1991–2026 (n = 36), Jeffreys point estimate.
- **F1, ENSO-conditional:** Januaries with DJF ONI ≥ 1.0. That's roughly 8
  winters, too few to trust alone.
- **F2, primary:** F1 shrunk toward F0 with 10 pseudo-years,
  `(k₁ + 10·p₀) / (n₁ + 10)`.
- A 2006–2026 subset is reported as a warming-trend sensitivity. It isn't
  scored.
- E1 counts are bucketed {0, 1–2, 3–5, 6+} with the same three forecasts.

## Scoring

- **Binary events:** Brier score per event for F0, F1 and F2.
- **E1 buckets:** ranked probability score.
- **W1** is scored only if the proxy correlates with our actuals at
  r ≥ 0.6 (daily, both winters). Otherwise it's reported as unvalidated.
- **Outcome data:** ERA5 via the same pinned source, retrieved on or after
  10 Feb 2027. The retrieval time is recorded, and ERA5T-to-final revisions
  are noted if found.

**Primary prediction:** F2's Brier score summed over E1–E3 is lower than
F0's. One January is one observation, so this goes on a running record.
A single winter can't establish skill in either direction, and it won't be
presented as if it does.

## What the outlook says in market terms

Directional only, with no dollar figure.

- An E3 run is the Fern-type scenario. Payout concentrates in a few days, and
  counterflow obligations are the exposed side.
- A W1 lull without E1 is a residual-demand scenario. Its path effects
  aren't validated here.

Either way, the outlook explains January. It doesn't size a position.

## Freeze procedure

```bash
.venv/bin/python -m strategy.winter_outlook --freeze --cpc <transcribed CPC context>.json
```

This writes `docs/outlooks/JAN2027-weather-outlook.json`, which is refused
if it already exists. The SHA-256 is added below in the freeze-day commit.
Every outcome gets published, the same way as before.

## Addendum, same day: dry run (no rule changed)

The builder was run once after the rules commit (`388ef33`) to check it
works. No January 2027 data exists yet, so it computed historical base rates
only. Three notes:

- The ONI ≥ 1.0 set holds **5** Januaries (1992, 1998, 2010, 2016, 2024),
  not "roughly 8". F1 alone is therefore very thin. That's why F2, the
  shrunk forecast, is primary. The rule is unchanged.
- `latest_oni` reported the last DJF row instead of the most recent season.
  This was a reporting fix only and touches no forecast.
- W1, as defined, happens in most historical Januaries. It's kept as
  registered. Any stricter lull definition would be added before the freeze
  as a dated, secondary event, never in place of W1.
- The wind proxy correlates with our SystemWide actuals at r = 0.85 over
  180 winter days, so W1 is scoreable under the r ≥ 0.6 rule.

## Addendum, 15 Oct 2026: a stricter secondary wind lull (W2)

Added at Tim's request before the freeze. W1 stays as registered and scored.
W2 is **secondary**.

- **Rule:** W2 is a run of at least *d* consecutive days with proxy wind
  capacity factor below *c*. *d* is one of {3, 4, 5} and *c* is one of
  {0.05, 0.075, 0.10, 0.125}.
- **How the pair is chosen:** the pair whose base rate over the training
  Januaries (1991–2026) is closest to 20% wins. Ties go to the longer run,
  then the lower threshold.
- **Reproducibility:** selection is mechanical, in `choose()` in
  `strategy/winter_outlook.py`. The full grid of base rates is written into
  the frozen file.
- **Scoring:** at scoring time the threshold is read from the frozen file and
  never refit. W2 is scored only under the same r ≥ 0.6 proxy rule as W1.

## Addendum, 15 Oct 2026: F2 formula corrected before freeze

The registered F2 formula, `(k₁ + 10·p₀)/(n₁ + 10)`, mixed a raw ENSO count
with a smoothed climatology. When the ENSO count is zero, the result falls
below **both** F0 and F1. The November dry run showed this for freeze days:
F2 0.008, against F0 0.014 and F1 0.062. That contradicts the registered
intent, "F1 shrunk toward F0".

F2 is now `(n₁·F1 + 10·F0)/(n₁ + 10)`, using the smoothed F1 and F0, so it
always lies between them. It applies to both outlooks and to the E1 buckets,
and is implemented in `shrink()`. The change was made before either freeze.
No target-month data exists or was used. For January it moves E1 from 0.359
to 0.364 and E3 from 0.196 to 0.202.

W2's selected threshold for January is ≥ 5 days below CF 0.125, with a base
rate of 0.139 over 1991–2026. A 3-day run below 0.05 tied, and the tie rule
picked the longer run. Since 2006 only about 2% of Januaries had a W2 lull,
so climatology may overstate it. The trend check records this.
