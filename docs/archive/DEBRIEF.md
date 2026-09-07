# Debrief: why most of the research failed, and what to do instead

Written 1 Aug 2026, after a session in which roughly six findings died under
testing and one partially survived. The strategy note that prompted this —
"make the unit of research a constraint, not a node" — explains the failures
better than my own post-mortems did.

## What I actually did

Started with 1,027 nodes and hunted price correlations. Nearly every test was
node-level pattern-matching:

| test | result |
|---|---|
| local weather vs node basis | died on independent classification |
| XWOLF1's 64% win rate | one month of noise |
| energization overweight | real (p<0.0001) but GBP does 2x more and loses |
| hybrid vs standalone fixed rule | inverted out-of-sample in January |
| trailing-history path screen | lost 5x the universe in January |
| PTDF valuation | corr −0.065; wrong network vintage |
| relative-value ratio signal | **partially survived** (placebo p=0.020) |

The pattern is not random. **The one thing that survived was the only test
framed as disagreement** — auction price ratio versus trailing realised ratio —
rather than as "what paid well historically". Everything framed as "find the
profitable nodes" broke on contact with a regime change.

## Where the advice lands

**1. Unit of research.** I had this backwards for the whole session. The
constraint-level fact I did find — top 10 constraints carry 47% of $172.7M
monthly rent — arrived late, from Steve's operations report, not from design.
That single number reframes the problem from 35,000 paths to ~30 objects, and I
should have started there.

**2. Hunt disagreement, not high prices.** I repeatedly ranked by historical
payout. The advice says explicitly that a high historic payout alone fails the
test, and my results agree: every historical-payout screen died.

**3. Structural vs event books.** I conflated them badly — tried to force the
January congestion spike (an event) into a monthly CRR rule (structural). CRR
auction timing means event information arrives too late to express there. That
is a structural reason the hybrid rule *had* to fail, independent of the data.

**4. Evidence score.** I had no such framework. Ranking was by backtest return,
which is precisely the failure mode.

**5. Negative knowledge.** Accidentally accumulated (see LOCATION_RESEARCH.md's
ruled-out list) but never organised for trading. This is cheap to formalise and
prevents re-learning the same bad trade each season.

**6. Autocorrelation as symptom.** The DA-over-RT premium measured yesterday
(+$1.38/MWh at hubs, ~+$4.00 at nodes) is very likely the "noisy risk premium"
the advice warns about. I flagged the risk but did not do the decomposition:
which constraint, what unabsorbed driver, repeatable at the same decision
timestamp, survives controls for outages/forecast revisions/hour/scarcity.

## What is worth keeping

Everything durable from the session was a **measurement or a piece of
infrastructure**, not a strategy:

- `settlement_point -> PSS/E bus`, 1,027/1,027, exact
- node technology tagging from the GIS queue (162 hybrid, 106 standalone, ...)
- **1,031,615 constraint rows**, 1 year, 5-min SCED, with shadow prices and
  from/to stations
- PTDF engine, verified (slack=0, self-sensitivity 0.88, orientation handled)
- constraint station -> bus join at 64% of economic weight
- measured forecast bias: ERCOT over-predicts wind everywhere, −6.4% system,
  −17% Panhandle, over 2 years
- measured DA premium: +1.26..1.82 at hubs, ~+4.00 at nodes, tails all LZ_SOUTH

That is exactly the input list a constraint-intelligence layer needs. The
machinery is right; it was pointed at the wrong unit of analysis.

## Corrections from the second review (1 Aug)

**Exposure estimation is empirical, not PTDF-first.** The hard part of a
constraint card is knowing which nodes move when the constraint binds. Our
PTDF attempt failed on network vintage — but the empirical version needs no
network model at all: regress nodal prices on the constraint's binding state
across a year of 5-minute history. The statistical layer is not discarded; it
becomes the measurement instrument inside each card. We hold both inputs
already (1.03M constraint rows, 2 years of nodal prices), so this is runnable
today, unlike the PTDF path which waits on an SSWG case.

**Congestion is not the whole DART.** ORDC adders and reserve shortfalls are
system-wide scarcity, not a constraint story. Without separating them, scarcity
days get misattributed to whichever constraints happened to bind that day and
pollute every card. We ingest none of the adder feeds (NP6-322/323/324) yet.
The Jan-2026 "congestion spike" in our seasonal test plausibly contains
scarcity P&L we mislabelled — worth re-checking once adders are loaded.

**Evidence scores drift subjective.** Every component must be a number the
pipeline computes, and the composite score gets backtested like any signal.
No hand-tuned weights.

**Point-in-time applies to constraints too.** Our binding_constraints backfill
has exactly the vintage flaw the price tables have: ingested_at is the backfill
time, so as-published vs as-corrected cannot be distinguished for history. Live
collection from now on carries real vintages; backtests on the backfilled year
must state this.

**Agreed build order** (working signal first, cards grow underneath):
SCED+DAM constraint ingestion (done) -> empirical exposure estimation ->
constraint cards -> disagreement score -> export. Negative-knowledge book
starts now as a plain append-only table.

## Known blockers, stated plainly

- **Network vintage.** The only RAW case we hold is April 2028 planning. PTDF
  exposure computed from it does not describe 2025/26 prices. Needs a
  contemporaneous SSWG seasonal case (MIS request).
- **No outage data.** Nothing ingested. Outages are a primary driver of whether
  a constraint binds, and their absence caps how good any physical-likelihood
  estimate can be.
- **Constraint history is 1 year.** Enough for frequency, thin for seasonality.
- **DART requires QSE.** Every firm that beat the CRR market holds one; the one
  that lost does not. Whether that trade is available at all is a registration
  question, not a research question.
