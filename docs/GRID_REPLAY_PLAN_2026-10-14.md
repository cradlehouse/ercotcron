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


## Addendum — 14 Oct 2026: weather integration and test clarification

This addendum preserves the original registration above. It clarifies the
information sets, weather experiments and validation requirements before replay
results are evaluated. Where the original wording conflicts with this addendum,
this addendum governs. It records design decisions, not completed ingestion,
verified data coverage or demonstrated forecast skill.

### Separate reconstruction, day-ahead and month-ahead tests

- **A1 physical reconstruction:** actual unit output and realized outages test
  whether the network representation reproduces operating conditions. Realized
  SCED dispatch is not evidence of an ex-ante DAM congestion forecast. Score
  operating-state reconstruction separately from DAM prediction, and document
  the differences between the monthly CRR model and operating topology.
- **B1 day-ahead prediction:** use forecasts demonstrably available before the
  relevant DAM decision. This is a separate horizon from the monthly auction.
  Day-ahead forecasts published after the monthly auction cannot be used to
  demonstrate month-ahead CRR forecasting skill.
- **Month-ahead prediction:** use only weather guidance, outage announcements,
  upgrade schedules, network information and trained model artifacts available
  by the applicable auction decision cutoff. Forecast the delivery month using
  scenarios rather than assuming its eventual daily forecasts were known.
- **B2 forecast misses:** actual-minus-forecast values are diagnostic outcomes.
  Their historical distributions may inform future error scenarios when fitted
  on training data; realized future misses cannot be decision-time predictors.

Every run must identify its horizon, exact information cutoff, source manifest,
model version and comparison baseline. Initialization time is not necessarily
publication time. Reanalysis is suitable for historical attribution but must
not silently substitute for a contemporary forecast or observation available
at the decision cutoff.

### Weather model requirements

**B3 regime probabilities.** CPC temperature and precipitation categories do
not directly give probabilities of joint regimes such as high West wind with
low load. Estimate regime frequencies from calibrated weather scenarios or a
training-only statistical mapping. Preserve regional and temporal dependence
among temperature, humidity, wind and solar radiation. Test ENSO's incremental
contribution beyond seasonal guidance that already incorporates it.

**B4 regional demand.** Include humidity, hour/day/holiday effects, regional
load growth and nonlinear heating/cooling response. Verify actual-load history
and its geographic correspondence before fitting. Weather zones and settlement
load zones are not interchangeable. Prior 7/30/60-day conditions and the latest
completed month are candidate features; a partial month must be labeled as
such and all windows must end at the information cutoff.

**Available versus delivered generation.** Weather predicts available wind and
solar production. Curtailment, plant availability and dispatch determine how
much is delivered. Do not interpret curtailed generation as a direct measurement
of wind or solar resource. Normalize for contemporaneous fleet capacity and
retain a documented resource-to-bus mapping.

**F1 joint scenarios.** Preserve dependencies between weather, generation and
outages where supported by data. Do not sum independent expected outage effects
as though simultaneous failures and nonlinear congestion responses disappear.
Balance injections and withdrawals through a documented dispatch/balancing
rule. Calculate net load and path outcomes within each scenario, then summarize
the resulting distributions; separate marginal quantiles cannot simply be
subtracted or added to obtain system or portfolio quantiles.

### Added experiment: weather by topology

For a small, predefined set of well-mapped constraints, cross the same set of
weather/injection scenarios with two network configurations:

1. Reference topology.
2. Topology containing the planned outage or upgrade.

Hold weather and injections constant to isolate the modeled topology effect;
hold topology constant and vary weather to isolate the weather effect. Where
redispatch is modeled, use the same dispatch rule and label that experiment
separately from a fixed-injection sensitivity comparison.

Measure changes in flow direction, loading, binding occurrence and affected
paths. This tests whether a quiet corridor reflects weather, structural change,
or their interaction, and identifies upgrades/outages whose impact depends on
regional wind, solar or demand. Historical comparisons are model-based
attribution, not proof that every omitted operating factor was controlled.

The first weather pilot is B3 plus C1 interactions on these selected constraints.
Validate congestion direction and occurrence before attempting dollar value.
Select the constraints and events using a recorded rule before scoring, rather
than choosing only memorable successful examples.

### Data coverage gate

Treat the original 'already in hand' list as claims to verify, not proof that
each dataset is complete or suitable for every test. Before fixing eligible
windows, produce a manifest containing:

- Source/product, variables, geography and units.
- First/last valid dates and missing intervals.
- Forecast initialization, publication/availability evidence and revision status.
- Actual versus forecast versus reanalysis classification.
- Network model purpose, effective dates, ratings, contingency coverage and
  resource/bus matching completeness.

Load forecasts listed as starting in April 2026 cannot support B1 throughout
the October 2024–September 2025 tuning period without another archive. Forecast
vintages collected from October 14, 2026 onward do not establish historical
vintage coverage. Check ERA5/CPC artifacts and their release metadata directly.
Actual-load coverage is a separate dependency from load forecasts.

Choose comparable test windows for each eligible variant and its baseline.
Record any coverage-driven date change before examining its test outcomes;
never silently shrink the evaluation to successful or convenient months.

### Expanded scoring and economic interpretation

Retain the maximum of four promoted variants, with all selection performed on
tuning data. Name and freeze each variant, its features, event selection,
metrics, baseline, missing-data rules and acceptance criteria before scoring.

- **Constraint occurrence:** report precision and recall, false alarms, missed
  events and binding-hour errors. For probabilistic outputs, report probability
  calibration and a proper probability score. Hit rate alone can reward
  predicting too many constraints.
- **Constraint identity:** match monitored element and contingency where
  applicable; document unresolved mappings instead of treating all similarly
  named lines as the same constraint. Loading near a rating is a stress proxy,
  not proof of economic binding under the relevant security constraints.
- **Shift events:** evaluate direction and magnitude around the predefined
  events, including failures and ordinary comparison periods.
- **Path outcomes:** report rank correlation, dollar error and uncertainty
  calibration by instrument and TOU, using appropriate congestion quantities.
  Apply option payoff rules within each scenario before averaging. Distinguish
  physical flow sensitivity from the additional dispatch/economic assumptions
  required to forecast shadow prices and dollar values.
- **Robustness:** report results in both historical test halves, by delivery
  month, and excluding the single largest contributing event. Cluster
  uncertainty by month/event rather than treating correlated paths as
  independent evidence. Show concentration in shared weather/grid exposures.
- **Auction relevance:** incremental payout forecasting and executable auction
  performance are separate claims. Any trading evaluation must include
  availability, fills and costs under assumptions fixed before evaluation.

Add a forecast-error sensitivity check: perturb regional load, wind and solar
using errors estimated only from eligible training data. Identify predictions
whose direction or apparent value disappears under modest input changes.

### Historical exposure and forward validation

October 2025–September 2026 remains the proposed frozen historical evaluation
window, subject to coverage. Parts of that period, including specific grid
changes and September outcomes, have already been examined in prior research.
It must therefore be described as historical validation with prior exposure,
not a pristine untouched holdout. The SHA-256 freeze protects the new replay
specification from subsequent tuning; it does not undo earlier exposure.

The two-half baseline requirement remains a historical screen, not sufficient
by itself for promotion to live bidding. Independent forward evidence is also
required. Freeze live predictions before the relevant auction decision cutoff,
not merely before the delivery month starts. November 2026 qualifies only if
its applicable cutoff has not passed when the prediction is frozen; otherwise
start with the next eligible auction. Do not backdate a prediction.

Published predictions and their input manifests remain immutable. Corrections
create linked new versions. Any rule changes after evaluation require a dated
addendum and new independent validation rather than rerunning the same year
and describing it as untouched.

### Revised immediate sequence

1. Preserve forecast vintages and verify the source/network coverage manifest.
2. Establish A1 reconstruction and A2 baseline behavior on a small tuning-only
   pilot, with explicit operating-versus-auction model limitations.
3. Add the B3/C1 weather-by-topology experiment and forecast-error sensitivity.
4. Freeze at most four eligible variants and their scoring rules; run the
   historical evaluation once and report prior exposure and coverage limits.
5. Begin independently frozen auction-cutoff predictions and score them after
   delivery. Expand valuation/UI and consider ticket integration only after
   the appropriate physical, forecasting and forward-evidence gates pass.

## Addendum — 14 Oct 2026 (evening): coverage-driven window change, before any replay is run

Recorded before any reconstruction or forecast result exists.

**Coverage found:**

- Monthly CRR network models are held only for OCT 2025, NOV 2025, DEC 2025,
  JAN 2026, FEB 2026 and APR 2026. Each comes with its contingency,
  monitored-element and non-thermal files, supplied from the MIS secure area.
- No model exists for any month of the registered tuning window
  (Oct 2024 – Sep 2025).
- Replaying that window on a later grid would use the wrong topology. The
  original registration rules that out.

**Revised windows:**

- **Tuning:** Oct 2025 – Jan 2026. Four models.
- **Historical evaluation:** Feb 2026 – Sep 2026, run once under the existing
  freeze rules. It needs the MAR 2026 and MAY–SEP 2026 models, which have been
  requested. Months without a model are excluded, not substituted.
- **Live forward:** unchanged. Freeze before each auction cutoff, once the
  matching monthly model is held.

These months overlap work already examined: the Sep–Oct 2026 grid changes,
and the event study, which used Feb 2025 – Jul 2026 projects. The historical
evaluation is therefore prior-exposed. Live forward results carry the
independent evidence.

If OCT 2024 – SEP 2025 models are obtained before tuning results are
examined, the original split may be restored by a further dated addendum.

**Inputs now in place:**

- **Injections:** 60-Day DAM Disclosure, hourly, Oct 2024 – Aug 2026.
  Covers resource awards, virtual offers and bids, and PTP awards.
- **Decision-time forecasts:** ERCOT's archived load, wind and solar
  editions as posted at 09:30–09:55 Central, Oct 2024 onward (loading).

## Addendum — 15 Oct 2026: walk-forward paper trading, one month at a time

Recorded before any paper-trade result exists, at Tim's direction.

**Method.** Trading tests walk forward one auction at a time:

1. Build and tune on earlier months.
2. Construct one month's paper bid using only information available at that
   auction's cutoff.
3. Freeze the bid by SHA-256.
4. Score it after the delivery month settles.
5. Review and adjust, then construct the next month.

No month is scored in bulk. Untested months stay untouched for later.

**Information-set rule.** The 60-Day DAM Disclosure is public 60 days after
each operating day, so a bid at cutoff T may use DAM injections only through
about T−60 days. Other inputs are limited to what was published by T:

- decision-time load, wind and solar forecast editions;
- the outage data then published;
- the network model for the delivery month;
- auction results already posted.

**Sequence:**

- **Build and tune:** Oct–Dec 2025. Already examined in the A1 reconstruction.
- **First paper month:** FEB 2026 delivery, auction held Jan 12–14 2026,
  information as of Jan 11 2026. JAN 2026 is excluded as a trading test
  because its reconstruction scores were examined on 14 Oct.
- **Next:** APR 2026 (no MAR 2026 model held). Then each further month as
  models arrive, each only after the previous one has been reviewed.

**Each paper month is scored on:**

1. Realized DAM payout of the paper paths minus their auction clearing cost.
2. The same against the history-only baseline at an equal budget.
3. Predicted-binding vs actually-binding constraints (precision and recall).

**Adjustments.** Changes between months are recorded here, dated, before the
next month is constructed. A month already scored is never re-run as if
untouched.

## Addendum: paper-month slate (15 Oct 2026, before any month is frozen)

Each paper month freezes a slate of books together, not one or two, so every
month we spend tests as many ideas as possible. Built by
`strategy/paper_month.py`; the docstring is the authoritative definition.

- Signals: phys_base, phys_lull (-4 GW wind), phys_windy (+6 GW wind),
  phys_cold (-2 GW wind, load +15%), phys_robust (min of the four),
  phys_wxavg (mean of the four), phys_nofilter, phys_recent (latest 30
  disclosed days instead of last year), hist100, hist30, consensus
  (min of phys_base and hist100).
- Bid rules: m125, m150, m200 (value >= 1.25 / 1.5 / 2.0 x expected clearing,
  limit = value / ratio, top 60) and wide110 (1.1x, up to 150).
- random__control: 60 seeded random candidates bid at 1.5x expected clearing.
- 11 signals x 4 rules + 1 control = 45 books (all distinct on FEB 2026).
- Scoring per book: cleared bids at the actual auction price, then
  payout minus cost per MW, hit rate, and rank against random__control.
  With 45 books the best one is partly luck; a signal or rule earns trust only
  by beating the control in more than one month.
- Weather scenarios move wind by MW at the farms (DAM clears little wind), so
  they change flows; each element's $ scales with (scenario / base mean
  loading)^2, clipped 0.25x..4x. A first version (scaling DAM wind awards,
  frequency >= 90%) produced near copies of phys_base and was replaced in the
  dry run, before any freeze.

## Addendum: line trips, outage replacement and month order (15 Oct 2026, before any freeze)

- Contingencies: every element's loading is now the worst of its base case and
  every contingency in the delivery month's own contingency file (exact DC
  distribution factors, multi-element included; islanding contingencies
  skipped). Most DAM binding is post-contingency, so the base-case-only model
  is kept as its own signal (phys_n0) to measure what this adds.
- Units on planned outage are replaced by gas, pro rata system-wide (default)
  or in their own load zone first (phys_local), instead of vanishing.
- 13 signals x 4 rules + control = 53 books.
- Month order changed before any result was seen: MAR 2026 first (as of
  8 Feb 2026, results posted 19 Feb), then MAY, then JUL; FEB 2026 is held
  back as the last rehearsal before real money, ideally with Steve's
  transmission outage list. APR, JUN, AUG, SEP in reserve.
- Analog-month zonal load forecasts (NP3-560) backfilled for Mar-Sep 2025.

## Addendum: MAR 2026 result and the rules for MAY (15 Oct 2026, before MAY is built)

MAR 2026 (sealed, manifest sha256 06bacaf2...): random control +$88k; one
physics book above it (phys_n0__wide110 +$140k); every other physics book lost
(about -$150k to -$265k). Three paths from LARDVFTN_G4 (the Laredo VFT tie)
made $157k of phys_base__m150's $204k loss. Physics paths mostly paid in the
predicted direction (69% positive), but physics $ value had ~0 correlation
with payout, while the auction clearing price had 0.71-0.82.

Rules from MAY on (Tim approved 15 Oct; designed on MAR, so MAR cannot test them):
1. No DC ties (DC_*) or Laredo VFT (LARDVFT*) on either end.
2. At most 2 paths per source and per sink in a book.
3. Rank by $ edge (value - expected clearing), not value / clearing.
4. Candidates priced >= $0.25/MWh in the latest prior auction only.
5. Auction-anchored valuation: value = latest clearing x R, where R = what
   candidate paths paid / their clearing price over the delivery months
   completed inside the 100-day window to asof; physics tilts it by
   (1 + k x z), z = the path's physics value standardised across candidates,
   clipped +-2. k = 0.25 / 0.5 / 1.0 on phys_base; 0.5 on phys_n0, phys_windy,
   phys_robust, phys_recent. Pure physics value kept as one comparison signal
   (phys_base); market (R x clearing, no physics) and hist100 as baselines.

## Addendum: JUL 2026 slate (15 Oct 2026, before JUL is built)

MAY 2026 (sealed): every book lost (paths paid ~0.73x their clearing); best
returns phys-tilted anchored windy/robust (-14%) and pure physics (-15 to
-18%) vs market -27% and random -38%; hist100 -63% to -106%. Across MAR and
MAY (all candidates): paths priced $3+ paid 0.90x / 0.82x their price, the
$0.25-3 band 1.6-1.9x / 0.9-1.0x, and counterflow paths beat their price
69% / 62% of the time. MAY 2026 load matched its analog (May 2025) within
1%; MAR 2026 ran 4.2 GW (8%) above MAR 2025.

JUL rules (Tim approved 15 Oct): the MAY rules unchanged as the core, plus
1. Price cap: every signal is also bid with rules m125cap3 / m150cap3 - the
   same as m125 / m150 but only paths whose expected clearing is <= $3.
2. Load growth: g = mean day-ahead SystemTotal load forecast (NP3-561) for the
   30 days to asof / the same days one year earlier. Scenario "grow" = the
   base analog with load x g (gas fills it); signal anch50_grow.
3. Counterflow books: candidates whose latest prior clearing is between -$3
   and -$0.25; buy (be paid) with limit = 0.75 x expected clearing, i.e. only
   clear if paid at least 75% of the last price. cf_phys: ranked by physics
   edge (phys_base - expected clearing), node cap 2, up to 60; cf_random: 60
   seeded random from the same pool. Scored on profit (cost is negative).
JUL as of 7 Jun 2026 (results posted 18 Jun).

## Addendum: remaining months on the focused slate (15 Oct 2026, 17:15 CT, before any is built)

JUL 2026 (sealed, manifest 928d28ce...): the $3 cap beat the uncapped rule on
every signal (pure physics m150 -35% -> +194%; market m125 -20% -> +30%;
hist100 m150 +10% -> +53%); counterflow made money (cf_phys +$44k, 71% won;
cf_random +$30k); random control +19%.

Tim (15 Oct): make the cap and counterflow the default and run all remaining
months. Focused slate (--focused): signals phys_base, phys_windy, phys_recent,
anch25_base, hist100, market x rules m125cap3, m150cap3, plus random__control,
cf_phys__keep75, cf_random__keep75 (15 books). As-of = 11 days before each
auction's results posting, as for FEB-JUL:
  FEB as of 2026-01-11, APR 2026-03-08, JUN 2026-05-10, AUG 2026-07-12,
  SEP 2026-08-09.
FEB is no longer held back (Tim's call); it is scored like the rest.
NOV 2026: paper only - built after the 5pm CT 15 Oct auction close, frozen
before results post; as of 2026-10-15 on the OCT 2026 CRR model (the NOV model
has not been received), flagged model_month=2026-10 in its manifest. Scored
when NOV DAM prices are complete (Dec).

Correction (15 Oct, 17:30 CT): the builder chose "the two latest prior
auctions" by comparing auction names as text, which does not sort by date.
MAR and MAY used the right auctions; the sealed JUL used FEB+APR 2026 instead
of MAY+JUN (older prices, nothing from after asof - a valid but handicapped
test; it stays sealed and is not rebuilt). Fixed to compare dates and require
results posted by asof before any remaining month was built. FEB stays held
back: it is built and sealed tonight but NOT scored (Tim, 15 Oct).

## Addendum: results of the remaining months (15 Oct 2026, evening)

Sealed and scored on the focused slate: APR, JUN, AUG, SEP. FEB sealed,
unscored (holdout). NOV sealed as paper (OCT model). Over APR/JUN/JUL/AUG/SEP:
random control +$363k (4/5 months profitable); market <=$3 +$292k (3/3 active
months); pure physics <=$3 +$12k to +$18k; anchored physics -$41k to -$139k;
hist100 <=$3 -$27k to +$16k with +-$480k swings; counterflow physics -$257k,
random +$11k. Conclusion: broad diversified buying captured a 2026 risk
premium; physics did not beat random selection. Note: the focused slate's
phys_windy / phys_recent names matched no signal, so those books were not
built (11 books, not 15).
NOV $150k pot (paper, sealed separately as paper_2026-11_PeakWD_pot150):
union of the NOV market <=$3 and random baskets, equal MW per path, max
authorised <= $150k. Path list kept in the archive only (public repo).

## Addendum: winter and late months, and the physics veto (15 Oct 2026, before any is built)

Tim approved (15 Oct): run JAN 2026 (as of 2025-12-07), DEC 2025 (2025-11-02)
and NOV 2025 (2025-10-12) now, and OCT 2026 (2026-09-06; scored once October
DAM prices are complete). FEB 2026 stays the unscored holdout; OCT 2025 is
skipped (the AUG 2025 auction is not in the data). NOV 2025-JAN 2026 were
tuning months for the line-level precision check (which elements bind), but
their path payouts against auction prices were not examined in this work.
Analog-month zonal forecasts (NP3-560) backfilled for Oct 2024-Jan 2025 first.

Slate changes for these months (focused slate):
- Physics veto: candidates whose physics edge (phys_base value - expected
  clearing) is in the bottom 20% are removed. market_veto = the market signal
  without them (rules m125cap3 / m150cap3); vetorand__control = 60 seeded
  random paths from the vetoed pool at 1.5x expected clearing. Compared with
  market and random__control, this measures whether physics adds value as a
  filter.
- phys_windy and phys_recent now produce books (the earlier name mismatch is
  fixed).

## Addendum: winter results (15 Oct 2026, night)

NOV 2025 / DEC 2025 / JAN 2026 sealed and scored (OCT 2026 sealed, scored in
November). Market and market_veto made no bids (recent paths paid 0.79-0.99x
their clearing, below the 1.25x bar). Random control +$89k / +$12k / -$65k.
Pure physics (<=$3) lost in every book every month (-$9k to -$215k), winning
18-35% of paths vs 43-57% for random; load ran 5-11% above the analog year.
Physics veto (vetorand) beat random in 1 of 3. Physics counterflow -$454k in
JAN. Random control over all 10 scored months: +$409k, 7 of 10 profitable.
