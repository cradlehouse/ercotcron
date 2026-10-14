# Grid replay and congestion forecasting: plan and test design

Registered 14 Oct 2026, before any replay result exists. The commit carrying
this file is the timestamp. Changes after this date are dated addenda, never
edits.

## The question

Can we explain, then forecast, where the grid gets squeezed and how much
congestion is worth, better than assuming the past repeats?

The current method (history-only) is the baseline every variant must beat.

## Test design

| Stretch | Months | Use |
|---|---|---|
| Tuning | Oct 2024 – Sep 2025 | Build and adjust every variant |
| Locked test | Oct 2025 – Sep 2026 | Run once, after the rules are frozen by SHA-256 |
| Live forward | Nov 2026 onward | Predictions frozen before each delivery month and scored after settlement |

The tuning stretch may move later if the 60-day unit-output archive or the
historical network models do not reach Oct 2024. Any such move is recorded here,
dated, and made before the locked test is touched.

Many variants means some will look good by chance. So:

- At most 4 variants are promoted from tuning to the locked test, chosen and
  named before it runs.
- The locked year is scored in two halves. A variant has to beat the baseline
  in both halves.

**What we score:**

1. Constraint hit rate: did the predicted-squeezed lines actually bind (DAM)?
2. Shift prediction: when something switched (an outage or upgrade), did we
   predict where congestion moved?
3. Path value: rank correlation and dollar error of predicted vs realized
   DAM path value, against the history-only baseline.

## Variants: different ways of seeing the same grid

### A. Physics core

- **A1 Replay.** Actual unit output (60-day disclosure) plus outages, run as a
  DC power flow on that month's CRR network model. Lines at or near their
  rating count as squeezed.
- **A2 Shift factors only.** Skip flows. Value each path as the sum of its
  shift factors times each constraint's expected shadow price. This is cheaper
  and is how ERCOT itself clears the auction.

### B. Weather: forecast vs actual

- **B1 Forecast state.** Drive the replay with the day-ahead wind, solar and
  load forecasts, not the actuals. DAM prices, and so CRR payoffs, form on
  forecasts.
- **B2 Forecast miss.** Actual minus forecast, for wind, load and temperature.
  This tests how much DAM congestion surprise comes from forecast error. Most
  of it should land in real time, not DAM, which is itself worth confirming.
- **B3 Weather regimes.** Classify each day: high West wind with low load,
  low wind with high load, freeze, heat. Learn which constraints bind in each
  regime. A month forecast then becomes a mix of regimes, with weights taken
  from the seasonal outlook.
- **B4 Temperature to load.** Map temperature (actual and forecast, ERA5 and
  CPC) to zonal load shifts, then through the shift factors to constraints.
  Freeze days are the extreme case.

### C. Outages: planned vs by mistake

- **C1 Planned.** Known in advance. Test whether the auction model already
  carries them (the lag question) and whether DAM prices them correctly.
- **C2 Forced (by mistake).** Individually unpredictable, but the rate is
  predictable by unit, fuel, age and season (e.g. Oak Grove trips
  repeatedly). Use an expected outage value: probability times the outage's
  node-map effect.
- **C3 Transmission vs generation.** Line outages move flow directly.
  Generation outages move injections. Score them separately.
- **C4 Upgrade lifecycle.** Construction outage, then energize, then
  redistribution. This extends the 27-project event study on the replay.

### D. Structural change

- **D1 New load.** Data centers and large loads (large_load_queue,
  node_energizations): where new withdrawal appears and which constraints it
  loads.
- **D2 New generation.** New wind, solar and storage interconnections, from
  GIS report bus numbers.
- **D3 Constraint lifecycle.** Rising and vanishing constraints (as in
  Oct 2026) treated as a state to track, not noise.

### E. Market views

- **E1 Auction vs DAM vs RT.** Where the auction's price lags realized DAM
  congestion: the trade signal the repo's constraint backfills were built for.
- **E2 Crowding.** Whether our candidate paths clear above their history once
  others bid them (the results-day monitor).

### F. Combinations

- **F1 Scenario stack.** Regime (B3), plus known outages (C1), plus expected
  forced outages (C2), plus structural changes (D1–D3), through the physics
  (A1/A2). This gives a distribution of path values, not a single number.

## Data dependencies

- **Monthly CRR network models**, ideally 12–24 months back. Steve is pulling
  these from the MIS secure area, along with the planned transmission outage
  list. Without per-month models, replays of older months use the wrong
  topology. In that case the locked test shrinks to the months we hold models
  for.
- **60-day SCED unit output.** Archive depth is to be confirmed.
- **Already in hand:**
  - DAM and RT constraints: Aug 2024 and Jul 2025 onward, respectively
  - resource outages: Dec 2022 onward
  - wind and solar actuals and forecasts: Jul 2024 onward
  - load forecasts: Apr 2026 onward only
  - ERA5 and CPC
  - the weather forecast vintage archive: Oct 14 2026 onward

## Order

1. Station geolocation (OpenStreetMap alignment).
2. 60-day unit-output ingest.
3. A1/A2 on tuning months.
4. B, C and D variants on tuning months.
5. Name at most 4 variants, freeze, then run the locked test once.
6. Live forward. Only a variant that passes the locked test goes near a bid
   ticket.
