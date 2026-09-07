# Where the money might be, what proves it, and in what order

Written 27 Jul 2026, after a day of loading and probing. Everything here is
either measured or explicitly flagged as unproven. Numbers without a source line
are from the local sweeps in this session and are reproducible.

---

## 1. What exists now

| dataset | coverage | rows |
| --- | --- | --- |
| Day-ahead prices | 24 months, 15 points | 263,160 |
| Real-time 15-min prices | 24 months, 15 points | 1,051,785 |
| CRR auction awards | 12 monthly auctions, ~987 points | 1,019,106 |
| Wind actual + forecast | 24 months, 6 regions | 106,218 |
| Solar actual + forecast | loading | — |
| Load forecast | 8 days, 9 weather zones | 1,944 |
| Binding constraints | live only | accumulating |
| Weather models (ECMWF/GFS/ICON) | code ready, table not yet created | — |

Two things to hold onto, because they shape every conclusion below:

**Prices cover 15 settlement points. Auctions cover ~987.** Anything requiring
realised prices is therefore stuck on about 2% of auction paths — and those 2%
are the liquid hubs, the part of any market most likely to be efficient.

**117,369 price revisions are recorded.** ERCOT restates prices after the fact.
Any backtest must read through `rt_spp_asof`, not the live tables, or it will
show profits that were never available.

---

## 2. The opportunities, ranked by evidence

### A. Off-peak congestion uncertainty looks unpriced — strongest lead

The auction sells options and obligations on the same path. An obligation pays
the congestion whichever way it goes; an option pays only when positive. The
premium between them is the market pricing uncertainty, and it needs no price
history, so it covers the whole nodal map.

Measured, August 2026, largest paths by volume:

```
HB_NORTH   → LZ_NORTH    PeakWD    premium +0.268   4,278 MW
HB_HOUSTON → LZ_HOUSTON  PeakWD    premium +0.302   2,689 MW
HB_HOUSTON → LZ_HOUSTON  Off-peak  premium +0.006   2,348 MW
```

27 paths above 50 MW price off-peak uncertainty at **under one cent**.

**Why that might be wrong:** off-peak in Texas is the wind-driven regime — the
hours with the highest and least predictable renewable output, and the hours
that produce negative prices. The market appears to be charging almost nothing
for uncertainty precisely when the underlying is least predictable.

**Status:** measured on the auction side, untested against realised volatility.

### B. Illiquid paths carry a 43% higher premium — the clearest "corner"

Across 12 auctions, 589 path/block combinations that persist for six months or
more:

```
top decile by MW     n=58  mean premium +0.6022
bottom decile by MW  n=59  mean premium +0.8644
```

Optionality costs substantially more where fewer people are trading. Two
readings, with opposite conclusions:

- **Rational** — thin nodal paths genuinely are more volatile, and the premium
  is fair compensation for real risk.
- **Exploitable** — it is an illiquidity premium, and a seller willing to supply
  optionality in unwatched corners gets paid for it.

**Distinguishing them requires nodal price coverage.** That single measurement —
extra premium against extra realised volatility — decides whether this is a
business or a mirage. It is the highest-value unbuilt thing.

### C. The premium is persistent, which is what makes any of it tradeable

`|mean premium| / sd across months` = **2.21** for nodal paths (n=582), 2.81 for
hubs (n=6, too few to lean on). Above 2 means a path's implied volatility is a
stable characteristic rather than noise — last month's premium informs next
month's. Without this, A and B would be observations rather than strategies.

### D. Wind forecast error is large, and concentrated where the power curve is steep

ERCOT's day-ahead wind forecast, measured at matched lead time (n=56 hours,
Panhandle):

```
ERCOT day-ahead forecast vs actual : r = +0.845
day-ahead error: mean +136 MW, sd 421 MW  = 21% of mean generation
```

That 21% is the raw material — it is what moves price between day-ahead close
and real time.

Turbine output is cubic between cut-in and rated, then flat, so a 10% wind speed
error is worth:

```
 1.7% of capacity at  5.0 m/s
25.6% at  8.9 m/s
52.9% at 11.1 m/s     ← the only band that matters
 0.0% above rated
```

And the three major global models disagree by **9 km/h on an average hour**,
which is **30% of capacity** once passed through that curve, up to 96% on the
worst hours.

**The synthesis:** do not try to forecast wind better than ERCOT — they see
turbine telemetry and outage schedules that no weather API does. Instead
identify hours where forecast wind sits in the steep band *and* the models
disagree. Those hours are structurally unpredictable, which makes price
unpredictable, which is a volatility trade rather than a direction trade.

### E. Firm-level behaviour is visible — unusual, and unused

`AccountHolder` in the auction file is **not anonymised**. 313 firms, every
award, every clearing price, twelve auctions. You can score who is consistently
right on which paths and see where conviction concentrates. Most markets do not
let you read the other participants' positions.

---

## 3. What is claimed but not yet trustworthy

**`crr_edge` says option buyers lost every month, t below −13.** That is either a
major finding consistent with known FTR auction-premium literature, or a bug.
`won 0%` across eleven auctions is too uniform to accept. Three specific checks
before anyone acts on it:

1. **Payoff uses the full price difference, not the congestion component.** CRRs
   settle on congestion; sink minus source also carries losses.
2. **Source/sink orientation.** If reversed, every option computes to near-zero
   payoff — which is exactly the observed pattern on WEST→PAN and WEST→WEST.
3. **The t-statistics are overstated.** They assume auctions are independent, but
   congestion on a path is serially correlated month to month, so the effective
   sample is well under 11.

**Hub paths are not demonstrated to be efficiently priced.** Asserted earlier in
the session; only 6 hub paths persist six months or more, which supports
nothing. The nodal findings rest on 582 and stand.

---

## 4. Run order

Gated on fetches so nothing runs on half-loaded data. Steps marked **no
dependency** can run immediately.

### Now — no dependency

| # | run | why |
| --- | --- | --- |
| 1 | Fix the weather migration (`weather_forecast` never created despite deploying) | Blocks every uncertainty test |
| 2 | Verify `crr_edge` — the three checks above | A wrong sign here poisons everything downstream |
| 3 | Score account holders on pricing behaviour (conviction, concentration) | Needs only auction data, already loaded |

### When solar finishes (~80 min)

| # | run | why |
| --- | --- | --- |
| 4 | Backfill load, 24 months | Last input to net load |

### When load finishes

| # | run | why |
| --- | --- | --- |
| 5 | `price_stack` — the supply curve, where p95 detaches from median | The break point is the single most useful number for predicting scarcity |
| 6 | `wind_sensitivity`, `wind_miss_impact` | $/MW of wind by hour, with r² so a steep-but-meaningless slope is visible |
| 7 | Test A: off-peak implied volatility against realised off-peak price variance | Decides whether the unpriced-uncertainty lead is real |

### The decisive build

| # | run | why |
| --- | --- | --- |
| 8 | **Ingest day-ahead prices for the nodal points appearing in CRR auctions** | Converts B from a hypothesis into a measurement, and lifts `crr_edge` coverage from 2% to most of the map |
| 9 | Test B: illiquidity premium against realised nodal volatility | The question that decides if there is a business here |
| 10 | Backfill binding constraints, 24 months (~2M rows) | Turns "this path pays" into "this path pays *because* this constraint binds" |

### Ongoing

| # | run | why |
| --- | --- | --- |
| 11 | Accumulate weather-model disagreement forward | No historical archive stored; the sample only grows from now |
| 12 | Re-run `crr_edge` monthly as auctions clear | Twelve is the minimum for a t-statistic to mean anything |

---

## 5. Constraints worth stating plainly

**Trading needs an ERCOT counterparty account and collateral.** CRR positions,
virtuals and batteries all require market access this project does not have. The
realistic role is to be the signal, not the trader — which suits a partner who
already holds CRRs and is deciding whether to move into energy.

**Backtest through `rt_spp_asof`.** Repeated because it is the single easiest way
to manufacture a strategy that never existed.

**Twelve observations is the floor, not the target.** Every t-statistic here
should be treated as provisional until the sample doubles, and serial
correlation means the effective sample is smaller than the row count suggests.

**The liquid paths are the wrong place to look.** Every strong result so far came
from the nodal tail, and the one place the data is thinnest is the one place a
mispricing is most plausible.
