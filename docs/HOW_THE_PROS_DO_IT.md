# A practical framework used by sophisticated nodal/CRR desks — synopsis

Written 2 Aug 2026, revised after external review. Sources at the bottom.

**Read the sourcing critically.** The vendor material (Yes Energy, PCI) is
product marketing, not independent evidence of a universal desk process. It
describes a framework that sophisticated desks are *sold*, which is weaker than
evidence that they all run it. The academic sources are load-bearing; the vendor
ones are directional. Where a claim is our own measurement, it says so — and
several of our measurements are still unvalidated.

---

## 1. The framework's central claim

The vendor view — again, marketing rather than survey evidence — is consistent,
and it matches what our own week of testing forced us into independently:

> the competitive edge comes from congestion forecasting, weather analytics and
> short-term transmission modelling rather than simple directional congestion
> bets — it is less about "predicting congestion" and more about identifying,
> quantifying and monitoring the **drivers** of congestion before they show up
> in prices. (Yes Energy)

Restated: **do not model prices, model the physical causes of prices.** This is
the same conclusion our failures produced independently — every price-pattern
rule we built died out of sample; the only thing that held (96% sign agreement)
was the physical constraint→node exposure map.

## 2. The two modelling schools

**Production-cost simulation (the incumbent method).** Run an SCUC/SCED
simulation of the delivery period on a network model with forecast load,
generation, fuel prices and a planned-outage schedule. Read the resulting
shadow prices and LMPs; value each path as the simulated congestion. This is
what the large desks and the vendor tools (PLEXOS, PROMOD, UPLAN) do.

- Strength: handles topology change, new generation, and outages natively.
  It answers "what if" rather than "what was".
- Weakness: enormous input burden, and it is only as good as the outage and
  load assumptions. Garbage in, confident garbage out.
- **Our status: UNVALIDATED, cause not established.** Our PTDF engine scored
  corr −0.065 against realised nodal basis. An earlier draft attributed this to
  network vintage (our only case is April-2028 *planning*). That is one
  hypothesis among several, and it has not been tested. Also open: node-to-bus
  mapping errors, constraint naming/renaming, sign and per-unit conventions,
  missing contingencies, loss treatment, target mismatch (modelled congestion
  vs basis-to-system-mean), and comparison horizon. The engine should be
  treated as unvalidated until those are individually closed.

**Statistical/empirical (what we can actually run today).** Skip the network
model. Regress observed node basis on observed constraint shadow prices to
learn exposure empirically, then condition on regime.

- Strength: no network vintage problem, no input burden, and the exposures are
  measured rather than assumed.
- Weakness: cannot anticipate a *new* constraint or a topology change — it only
  knows constraints that have bound before.
- **Our status:** this is the validated exposure map. It is the one asset that
  survived out-of-sample testing.

Serious desks run both and use the simulation to catch what history cannot.

## 3. What the inputs actually are

Ranked by how much the literature and vendor material weight them:

1. **Transmission outages** — the single largest driver of a constraint binding
   unexpectedly. Planned outage schedules are the first thing a desk ingests.
2. **Load forecast and its revisions** — especially the revision *after* the
   day-ahead market clears.
3. **Renewable output and forecast error** — high-wind regimes flip the
   direction of flow on export-constrained corridors.
4. **Topology and network model changes** — new lines, re-ratings, and
   generation energisations, which permanently kill or create a constraint.
5. **Competitive intelligence** — who else holds the path, i.e. how crowded the
   trade already is.

**We hold 3 and 4. We do not hold 1 or 5, and 2 only partially.** That is the
honest gap list, and outages are the biggest hole.

## 4. Risk premium — and a distinction we got wrong

Academic work on PJM finds FTR auction clearing prices contain a **risk
premium** paid by hedgers to insurers, and that the premium *rises with the
number of participants trading the same path*. Crowded paths pay the
underwriter less; obscure paths pay more.

**Correction (external review, 2 Aug).** An earlier draft cited our node-level
DA-RT premium (~$4/MWh vs ~$1.40 at hubs) as evidence of this CRR premium. That
was an error and it matters:

- a **CRR** settles on the *day-ahead* congestion difference between source and
  sink;
- **DART** is a *real-time versus day-ahead* settlement discrepancy.

They share physical drivers but are distinct payoff processes. A DART average
says nothing directly about what a CRR earns. Our rare-vs-common constraint
result (+4.36 vs +0.03 $/MWh) is a **DART** measurement and should only be cited
as such until the equivalent is measured on CRR settlement.

**"Selling insurance" also needs direction.** Buying a positively-valued CRR
path is buying congestion protection; taking the adverse direction, or selling,
is underwriting it. Any claim about which side of the premium we are on must
first state the product (OPT vs OBL), the source→sink direction, the auction
payment, and whether the position is long or short. The earlier draft asserted
"selling insurance" without any of that.

What survives: the P&L shape is many small wins and occasional large losses, and
must be sized on expected shortfall rather than mean or Sharpe.

## 5. The risks the literature names

- **Locational congestion risk** — spatial nodal spreads (the thing being
  traded).
- **Temporal risk** — intra-day volatility.
- **Volume variability** — forecast vs actual generation/demand divergence.
- **Tail risk** — extreme-price and system-stress events.

The last one is where FTR books die. A path with a good average return and an
intolerable drawdown is the classic trap, and it is why win rate is a dangerous
metric here: our own DART fade backtest showed a **62% hit rate while losing
$54k/MW**, because the 38% of losses were far larger than the 62% of wins.

## 6. What separates the desks that persist

Synthesising the vendor material and our own firm-level measurements:

| trait | evidence |
|---|---|
| price discipline over congestion knowledge | GBP Power held paths with *more* realised congestion than Wolframium ($1.72 vs $0.98) and lost, because they paid $2.68 vs $0.73 |
| participation in the underlying market | **association only, n=5 firms.** Every firm beating the CRR market held a QSE registration; the one that didn't, didn't. QSE status also proxies for size, capital, information access and portfolio breadth — none of which we controlled for. Not usable as a desk-quality criterion. |
| breadth without crowding | Wolframium ran 601 endpoints; concentration into popular paths is what the risk-premium literature says you get paid least for |
| a memory of past mistakes | our negative-knowledge book is the deliberate version of this |

## 7. Where our approach currently sits

Aligned with best practice:
- constraint as the unit of research, not the node
- empirical exposure map, validated out of sample
- expanding-window walk-forward, fit old / test new
- distribution reporting (profit factor, worst hour, single-hour concentration)
  rather than mean and win rate
- explicit negative-knowledge record

Missing versus best practice:
- **transmission outage schedules** — the biggest single gap
- **contemporaneous network case** for the simulation leg
- **competitive intelligence** — who else holds each path
- post-DAM load/wind forecast *revisions* (RUC data now landing covers part)

## 8. Revised central thesis (after external review)

> Empirical constraint-to-node exposures are a credible trading asset for
> **known, stable** constraints. They are **not** a substitute for a current
> network model when topology, outages, generation or large load are changing.
> Their value decays with structural novelty.

So the empirical route is not doomed — it is **structurally incomplete**, and
the completion is a novelty-control layer rather than a better regression:

1. **Detect** topology, outage, capacity and load/generation changes.
2. **Suppress** historical exposure signals around affected clusters.
3. **Use PTDF/scenario analysis as a directional stress test only**, until a
   contemporaneous network case exists.
4. **Promote** a new constraint into the empirical map only after enough
   independent binding observations.

Structural-break detection therefore becomes the governing risk control, not a
refinement.

## 9. On competitive intelligence

Position data (who holds which path) is a legitimate **valuation and crowding**
feature. It is not evidence that another party "knows" a constraint will bind:
positions may be physical hedges, portfolio offsets, or liquidity provision.
Use for pricing discipline and crowding measurement; never as copied conviction.
Our own Wolframium/GBP comparison supports this — identical structural traits,
opposite outcomes.

## 10. Open diagnostics on our own headline claim

The "96% sign agreement" figure for the exposure map is under test. Nodes were
selected by |beta| on the fit window from ~1,117 candidates and then tested out
of sample, which inflates agreement. Running now: random-node control,
share of immaterial (|beta| < 0.02) observations, magnitude-weighted and
economically-weighted agreement, per-constraint breakdown, and beta-ratio
distribution. Until those land, treat 96% as an upper bound, not a result.

---

### Sources
- Yes Energy, [Improve Your FTR Trading Strategies with Competitive Intelligence](https://www.yesenergy.com/blog/improve-your-ftr-trading-strategies)
- Yes Energy, [What Is FTR Trading, and How Does It Work?](https://www.yesenergy.com/blog/what-is-ftr-trading-and-how-does-it-work)
- PCI Energy Solutions, [What Is FTR Trading? Strategies, Benefits & Market Impacts](https://www.pcienergysolutions.com/2024/08/07/what-is-ftr-trading-strategies-benefits-market-impacts-explained/)
- Oxford Institute for Energy Studies, [Risk Structure and Financial Hedging in Nodal Electricity Markets](https://www.oxfordenergy.org/wpcms/wp-content/uploads/2026/01/EL-61-Risk-Structure-and-Financial-Hedging.pdf)
- Oren, [Point to Point and Flow-based Financial Transmission Rights](https://oren.ieor.berkeley.edu/pubs/I.B1.127.pdf)
- CMU CEIC, [An options theory method to value Electricity Financial Transmission Rights](https://www.cmu.edu/ceic/assets/docs/publications/working-papers/ceic-06-03.pdf)
- Salthill Group, [Nodal (FTR/CRR) Trader role spec](https://www.salthillgroup.com/nodal-ftr-crr-trader/)
