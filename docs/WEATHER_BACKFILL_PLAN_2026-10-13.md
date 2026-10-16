# Weather backfill plan — 13 October 2026

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

Status: documented proposal. Public archive coverage was checked against provider documentation; no weather backfill, database migration, or new predictive backtest has been executed. Actual endpoint access, variable completeness, source retention, and commercial access requirements must be verified before bulk ingestion.

Companion: [Weather predictive review](WEATHER_PREDICTIVE_REVIEW_2026-10-13.md).

Application design: [Workflow, SQL, forecasting integration and UI](WEATHER_FORECAST_IMPLEMENTATION.md).

## Objective

Backfill enough weather and climate history to test whether prior-month conditions explain recent ERCOT congestion changes and improve month-ahead forecasts. Separately reconstruct the forecast information available before historical auction decisions. The first research deliverable is a weather-adjusted congestion/fade study; the seasonal and El Niño overlay follows once its inputs and validation are sound.

Historical weather answers why an outcome happened. Forecast archives answer whether it could have been predicted. These datasets must remain distinguishable throughout ingestion, feature construction, and scoring.

## Sources and coverage

| Dataset | Documented coverage | Intended use | Limitation |
|---|---|---|---|
| ERA5 historical weather | From 1940 | Temperature, humidity, wind, radiation, precipitation and land-condition history | Reanalysis reconstructs past conditions; it is not a contemporaneous forecast or purely station observations. Check each variable's availability. |
| ERA5-Land | From 1950 | Consistent land and soil-moisture history | Variable coverage differs from ERA5. Do not silently substitute one source for another. |
| CPC monthly/seasonal outlooks | October 1995 onward | Recover published temperature and precipitation outlooks before auction cutoffs | Archive formats and regional probability extraction require verification. A seasonal forecast is not three independent monthly forecasts. |
| CPC ENSO diagnostic discussions | Since 2001 | Recover contemporary ENSO assessments and expectations | Structured probability series may require separate source extraction; do not manufacture probabilities from qualitative prose. |
| Open-Meteo Single Runs | ECMWF IFS from March 2024; other models from April 2, 2026 | Retrieve the full horizon of individual short-term model runs | Confirm exact model, variables and initialization coverage. Initialization time is not necessarily public availability time. |
| Open-Meteo Previous Runs | Fixed-lead archive; dates vary by model | Evaluate short-term forecast errors by lead time | Verify selected models and lead offsets before choosing a test period. Not a month-ahead archive. |
| ERCOT wind, solar and load forecasts | Historical date queries exist in our collector | Recover forecast vintages and renewable actuals where the source still serves them | Source retention has not been audited. Current code keeps only the latest vintage and needs a separate archival ingestion path. |

Sources checked during the review:

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api).
- [Open-Meteo historical forecast dataset distinctions](https://open-meteo.com/en/docs/historical-forecast-api).
- [Open-Meteo Single Runs API](https://open-meteo.com/en/docs/single-runs-api).
- [CPC monthly and seasonal forecast archive](https://www.cpc.ncep.noaa.gov/products/archives/long_lead/llarc.ind.php).
- [CPC ENSO discussion archive](https://www.cpc.ncep.noaa.gov/products/expert_assessment/ENSO_DD_archive.php) and [archive coverage description](https://cpc.ncep.noaa.gov/products/expert_assessment/).

The Historical Forecast API stitches early hours of successive runs into a continuous series. It must not be presented as the forecast available at a historical auction cutoff. Use preserved individual runs or documented fixed-lead products for those tests.

## Backfill scope

### 1. Hourly weather overlapping market history

Target January 2024 through the latest available completed period, with at least 60 days of preceding history for rolling features. Verify the actual start and completeness of our market tables first; extend the weather window if needed to cover them.

Collect temperature, dewpoint or humidity, precipitation, shortwave radiation, cloud cover where available, 100 m wind speed/direction, and soil moisture. Pin a consistent reanalysis source and record units explicitly.

Use versioned site mappings for major load centers, wind clusters and solar clusters. Retain the existing 13 wind sites as a reproducible starting set, then document any additions. Load weather should be load-weighted; renewable weather should use appropriate fleet/location weights. Do not equate ERCOT weather zones with settlement load zones.

This dataset supports the initial question: after accounting for weather, available generation and outages, does recent weak congestion still look unusual?

### 2. Long climate history

Target daily weather from January 1991 onward, with warm-up history for rolling features. Derive monthly anomalies against a fixed 1991–2020 reference for descriptive climate analysis. For strict historical decision tests, use normals that were available at the cutoff or estimate normalization solely within training data.

Retain enough geography to distinguish the Panhandle, West, coastal/South and major demand regions. Aggregate daily data into degree days, precipitation, radiation, wind and soil-moisture summaries. This supports multiple ENSO-cycle comparisons without storing multi-decade hourly data everywhere.

Long weather history does not create long comparable power-market history. Fleet growth, transmission changes and load growth prevent treating historical El Niño years as directly transferable CRR price analogs.

### 3. Published outlooks and forecast vintages

First collect CPC and ENSO releases spanning the market-study period; extend backward for climate validation once extraction is reliable. Recover available individual short-term runs over the same period, choosing only those demonstrably available before each decision cutoff.

Probe ERCOT historical endpoints at a few representative dates before attempting a large vintage backfill. Preserve every distinct source publication if available. If history has expired, record the gap and start prospective collection; do not infer missing forecasts from actual outcomes.

## Data handling

Preserve raw responses/files, source URLs, retrieval timestamps, content hashes and a manifest of requested versus received coverage. Use restartable date/site chunks, bounded retries and idempotent writes. Establish provider access and quota requirements before selecting batch size.

Keep separate records for:

- **Weather conditions:** source/site, valid time, variable, unit, value, reanalysis or observation status, and known revision/publication information.
- **Forecast vintages:** provider/model/member, site, initialization, valid time, documented publication/availability time where available, retrieval time and value.
- **Climate outlooks:** release date, target month/season, geography, variable, probabilities or qualitative assessment, and ENSO index definition.
- **Decision features:** exact auction cutoff, delivery month, input lineage, coverage and model/version identifiers.

For a historical backfill, today's retrieval timestamp is not historical publication evidence. Mark availability as verified, conservatively estimated under a documented rule, or unknown. Exclude unknown-availability data from claims of exact decision-time forecast performance.

Do not write recovered vintages through the current latest-only weather/fundamentals upsert. Introduce archival tables or files first, then derive latest-value views for consumers.

## Prior-month and El Niño features

Build trailing 7/30/60-day features and the latest completed calendar month as of each decision. Label month-to-date separately. A September auction for November cannot use completed October conditions, even though October is the calendar month before delivery.

Candidate features include heating/cooling degree days, extreme-temperature hours, humidity, rainfall/soil-moisture anomalies, solar radiation anomalies, regional wind patterns and weather-adjusted load/generation residuals.

Record ENSO assessment release, expected strength/phase, target season and index definition. Distinguish ONI from RONI. Test whether ENSO adds predictive information beyond seasonal guidance rather than counting the same climate signal twice. Use current outlooks only for current decisions; historical tests require historical releases.

## Acceptance checks and research gates

1. Produce a coverage report by source, site, variable and time period, including missing intervals and available forecast lead times.
2. Verify units, UTC timestamps, ERCOT local delivery dates and daylight-saving transitions. Respect whether radiation values are instantaneous or interval averages.
3. Spot-check representative records against source responses; check ranges and duplicate keys. Preserve missing data as missing rather than zero.
4. Verify every forecast feature used in an auction simulation was available by its cutoff. Account for reanalysis publication delay and revisions.
5. Join physical outcomes to weather with consistent geography and contemporaneous capacity. Separate weather effects from curtailment, outages and topology changes where data permits.
6. Compare the existing baseline with antecedent-only, seasonal/ENSO-only and combined overlays. Respect existing holdouts; fit normalization and model choices on training data only.
7. Evaluate uncertainty by delivery month/weather episode, not by treating correlated paths as independent samples. Report physical forecast skill before claiming incremental auction value.

## Implementation order

1. Inventory market history and verify a small sample from each proposed archive.
2. Add raw archival storage, manifests and forecast-vintage preservation for future collections.
3. Backfill hourly weather over the market overlap and produce the coverage report.
4. Run the weather-adjusted fade study against the existing baseline.
5. Backfill long daily climate history and as-issued monthly/ENSO outlooks.
6. Recover available short-term runs and ERCOT forecast vintages; disclose irrecoverable gaps.
7. Freeze a prospective month-ahead shadow forecast before its auction cutoff and score it after delivery.

No production mark or bid adjustment is implied by completing the backfill. Promotion requires measured held-out improvement and a versioned methodology change. The immediate result is a reproducible research dataset and an evidence-based answer about the prior month's weather contribution to congestion.
