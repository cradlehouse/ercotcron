# Weather prediction review — 13 October 2026

> **Status, 15 Oct 2026.** Built so far:
> - The forecast-vintage archive (`weather_forecast_vintages`, cradlehouse/ercotcron#5, live since 14 Oct). It's site-level and append-only, and run times are labelled by source.
> - Two pre-registered physical outlooks, NOV 2026 and JAN 2027 (`strategy/winter_outlook.py`, `docs/preregistrations/`). They use pinned ERA5 history, are frozen before delivery, and never touch bids.
>
> Everything else here is a proposal and isn't built. That covers the other tables, RPCs, `/app/outlook`, path overlays and the payoff layer. Agreed order from here:
> 1. Explain performance: one return definition, plus concentration attribution.
> 2. The generation-adjusted fade study on existing wind/solar actuals.
> 3. A narrow temperature/radiation backfill, only for what generation can't explain.
> 4. A few shadow experiments.
>
> Forecasting UI gets built only if those tests show useful incremental information.

Implementation companion: [Weather backfill plan](WEATHER_BACKFILL_PLAN_2026-10-13.md), covering sources, history windows, data provenance, validation and rollout order.

Application architecture: [Workflow, SQL, forecasting integration and UI](WEATHER_FORECAST_IMPLEMENTATION.md).

The best next step is a month-ahead weather scenario overlay for CRR research, backed by preserved forecast vintages. The current stack collects short-term wind information but does not implement a seasonal predictive model. Prior-month conditions and ENSO should help describe the distribution of possible delivery-month outcomes; neither establishes a profitable path or a dollar adjustment by itself.

Scope: repository code, migrations, research notes, and current official climate guidance. No live database coverage audit or new predictive backtest was run. Historical research results below are attributed to repository notes, not independently reproduced. “Month before” is addressed both as antecedent weather and as the information available before the auction decision.

## Findings, in priority order

1. **Forecast history is overwritten, preventing valid historical forecast-skill measurement.** `ercot/weather.py:92–97` upserts on interval/region/model and replaces wind speed. It requests two past days, so a forecast originally stored ahead of delivery can subsequently be replaced with a later estimate. The weather schema has no model initialization or issuance timestamp. The `fetched_at` default is set on insertion; the updater does not refresh it. It therefore cannot establish when the current value became available. ERCOT fundamentals also retain only the latest vintage (`ercot/fundamentals.py`). Preserve original forecasts and observations separately before drawing predictive conclusions.

2. **The horizon and variables miss the monthly decision.** `ercot/weather.py:41–54` requests only 100 m wind speed, seven days ahead, at 13 sites across five wind regions. It collects no independent temperature, humidity, solar radiation, precipitation, soil moisture, or ENSO data. A seven-day forecast usually covers little or none of a CRR delivery month at its auction cutoff. There is no weather reference in the reviewed strategy or application consumers; the collector and SQL uncertainty view are presently a disconnected input.

3. **The uncertainty number is not calibrated.** `weather_uncertainty` takes the range of two or three deterministic model outputs, transforms regional average speeds with a generic turbine curve, and calls the result `power_spread`. Model disagreement is a candidate predictor, not a probability interval or measured ERCOT forecast error. Shared biases can make every model wrong together. Different run ages and missing models can change the range without changing atmospheric uncertainty. Archive run identity and score spread against actual errors by lead time, region, and season.

4. **Spatial aggregation loses information before the nonlinear transformation.** The Python collector uses equal site weights, despite the schema comment claiming capacity weights. It averages wind speeds before the power curve. In general, power of average wind speed is not average power. Preserve site-level speeds, apply calibrated site/cluster curves first, then weight by contemporaneous available capacity. Turbine availability and curtailment must be distinguished from meteorological forecast error. Missing sites currently suppress updates, leaving older values in the table; add coverage and age flags to prevent apparently complete mixed-age comparisons.

5. **The existing month logic is payout persistence, not weather conditioning.** `strategy/valuation.py:53–82` uses the median fitted month, the last three fitted months, prior occurrences of the target month, and a two-settled-month collapse check. It cannot distinguish weather-driven quiet conditions from a transmission change. `docs/MARK_METHODOLOGY.md` explicitly excludes forecast alpha and reserves the latest two months from calibration. Implement a separate, versioned shadow overlay; preserve the baseline and holdouts for a fair comparison.

## Prior-month conditions: what to add

For every decision timestamp, build both the latest complete calendar month and trailing 7/30/60-day features. An unfinished month is month-to-date, with its coverage explicit. For example, a September decision about November cannot use completed October weather. Calendar delivery-month-minus-one and the last observable month are not always the same.

| Feature | Predictive question | Treatment |
|---|---|---|
| Population/load-weighted heating and cooling degree days, temperature extremes and dewpoint | Was recent demand unusual because of weather or because load changed? | Fit nonlinear regional load response, including hour, weekday and trend; compare residual load after accounting for weather. |
| Precipitation and root-zone soil-moisture anomalies | Do antecedent land conditions improve next-month temperature/load forecasts? | Test lagged interactions by season; do not assume the same persistence in summer and winter. |
| Regional wind capacity factors, wind direction and low-wind duration | Was congestion quiet because generation patterns changed? | Normalize by available capacity; distinguish weather from curtailment and outages. |
| Radiation/clear-sky ratio and cloudy-day frequency | Did solar availability change, and does that help predict next month? | Normalize solar output for fleet growth and seasonal daylight; preserve regional differences. |
| Weather-adjusted constraint activity and path payout | Is a payout collapse consistent with ordinary weather variation? | Compare observed activity with a model trained strictly before the holdout; retain topology/outage evidence as separate explanatory inputs. |

These are hypotheses to test. Prior-month temperature alone is not a sufficient month-ahead forecast. The most valuable initial experiment is whether the recent congestion fade remains unusual after accounting for weather, available generation and outages. That can identify when the existing fade flag needs additional context without automatically reversing it.

## El Niño: current evidence and application

NOAA's 8 October 2026 discussion says El Niño is already present and strengthening, with greater than an 83% chance of strong-to-very-strong conditions through January–March 2027. Treat the coming winter impacts as the question, rather than assuming the event has yet to start. [NOAA ENSO discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml).

The 17 September seasonal outlook favors wetter conditions across the southern Plains. Its October–December temperature outlook assigns equal chances across a broad southern-Plains area, citing weak/conflicting signals. It also identifies the negative PDO as a reason this event may differ from the major historical El Niños. Therefore, do not impose a blanket colder-Texas adjustment or copy one historical winter. These are regional seasonal statements, not extracted probabilities for each ERCOT zone. [CPC seasonal discussion](https://www.cpc.ncep.noaa.gov/products/predictions/long_range/fxus05.html).

Proposed power-market scenarios below are physical hypotheses, not NOAA electricity forecasts:

- Cloudier periods can reduce solar generation and lift daytime residual demand, but rainfall totals alone are an inadequate solar proxy. Use radiation forecasts and cloud persistence.
- Cooler shoulder-season conditions can reduce cooling load; colder winter conditions can increase heating load. Estimate these separately by region and hour.
- Regional wind patterns and ramps may change. The sign of ERCOT wind generation cannot be inferred from the ENSO phase alone.
- Low solar combined with high load, low wind and outages matters more than any individual seasonal average. Preserve weather-variable dependence when generating scenarios.
- Weather changes congestion differently across paths. Translate scenarios through regional injections/withdrawals and validated constraint exposure, rather than attaching one ENSO multiplier to every CRR.

Store published ENSO phase probabilities, strength outlook, index definition (including ONI versus RONI), target season and release date. Include ENSO state/change as predictors alongside calibrated seasonal guidance. Avoid counting ENSO twice when the seasonal forecast already incorporates it. Use old El Niño years for weather-response evidence, not unadjusted price analogs: today's generation fleet, load and transmission differ.

## Proposed stack

| Decision horizon | Inputs | Output |
|---|---|---|
| Days 1–7 | Archived ERCOT forecasts plus site-level weather and ensembles | Load/wind/solar distributions, revisions and forecast errors |
| Days 8–14 and weeks 3–4 | CPC outlooks and calibrated subseasonal ensemble guidance | Weekly weather and net-load scenarios, with wider uncertainty |
| Delivery month / season | As-issued CPC monthly/seasonal probabilities, ENSO, seasonal model guidance, antecedent land/weather state | Regional distributions of degree days, renewable availability and constraint activity |

Build these data products first:

1. `weather_forecast_vintages`: provider, model/run, member if supplied, site, variable/unit, valid time, initialization time, publication/availability time where known, first-seen time, value and coverage. Preserve raw responses and hashes. If source issuance is unavailable, label first-seen explicitly; do not invent issue times from a fetch.
2. `weather_observations`: station/analysis source, valid time, publication/first-seen timestamps, revision status and units. Keep reanalysis identified as such.
3. `climate_outlook_vintages`: source/release, target month or season, geography, variable, below/near/above probabilities and index definition. A three-month outlook is not three independent monthly forecasts.
4. `weather_decision_features`: immutable feature snapshot tied to the actual auction cutoff, target delivery month, source vintages and model version.
5. `weather_shadow_predictions`: baseline comparison, regional scenarios, affected constraints/paths, uncertainty and subsequent scores.

Open-Meteo's Historical Forecast API stitches early forecast hours together; it does not recreate what was known at a historical auction cutoff. Its Previous Runs and Single Runs products are appropriate candidates for fixed-lead and individual-run reconstruction, subject to model-specific archive coverage. Use multi-decade reanalysis for climate relationships, while respecting its publication delay in decision backtests. [Open-Meteo archive distinctions](https://open-meteo.com/en/docs/historical-forecast-api).

## Validation and rollout

First compare four frozen alternatives: existing valuation baseline; baseline plus antecedent features; baseline plus seasonal/ENSO guidance; and their combination. Include a target-month climatology benchmark. Fit all normalizations and feature selection on training data only. Respect the existing two-month holdout and exact auction cutoffs; a source's valid date is not its availability date.

Use rolling delivery-month tests and leave-one-ENSO-event-out evaluation where historical coverage permits. Cluster uncertainty by delivery month or weather episode; thousands of correlated paths are not thousands of independent climate observations. The repository's July weather study had only 91 hours and no demonstrated predictive result. Its October notes describe roughly two years of power-market history: insufficient to establish an ENSO-specific trading edge across independent cycles.

Score physical forecasts first (load/renewable error, probability calibration, interval coverage), then incremental constraint/payout skill and executable auction outcomes. Check whether apparent gains survive changed fleet capacity, outages, costs, realistic fills, and exclusion of the single best month. ENSO improves the system only if it adds held-out information beyond seasonal guidance and the existing baseline.

Recommended order: preserve vintages and freshness now; add temperature/radiation/antecedent data; run the weather-adjusted fade study; then publish a frozen winter shadow outlook before its relevant auction cutoff. Promote to valuation only after measured incremental skill and a versioned methodology change. No production logic or published marks were changed by this review.
