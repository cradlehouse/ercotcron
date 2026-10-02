# Pre-registration — the deployment-book sales gate

**Registered:** 2 Oct 2026, before the NOV 2026 auction (bids Oct 13–15,
results by Oct 22) and before November delivery. The git commit carrying
this file is the timestamp.

**Sheet under test:** `NOV2026Monthly-hubshadow`, 34 rows frozen in
`sheet_snapshots` on 24 Sep 2026 by `strategy/hub_deploy_study.py`. The
rows are OBL, PeakWD/PeakWE, hub/zone-leg paths, limit = median month ÷ 1.5,
size = the market's average bought MW, capped at 25. The sheet is
admin-only and nobody bids it, so its fills are counterfactual: a row
"fills" when the auction cleared the path below our limit.

## The gate: no paid deployment seat is sold unless both pass

**G1 — fills (graded at NOV results, by Oct 22).** At least **14 of 34 rows
(≥40%)** clear at or below their limit. A book that rarely fills has no
depth to sell, whatever it would have paid.

**G2 — money (graded at NOV settlement, early Dec).** Across the filled
rows, `sum(realized) > sum(cost)` at the frozen suggested sizes. One month
is thin evidence. Passing G2 permits the first sale. It doesn't establish
the edge, and every sale carries the walk-forward's record beside it: 5 of
10 months lost, Jul–Aug carried the year.

## Outcomes

- **Both pass:** open 2 paid seats at $2,500/mo (docs/GTM_PLAN_2026-10.md §2B).
- **G1 fails:** Lane B stays research; the screen is re-examined for depth.
- **G1 passes, G2 fails:** no seats. December's book gets frozen as a second
  shadow and the gate repeats.

Whatever the outcome, it's published on the method page and in the record.
