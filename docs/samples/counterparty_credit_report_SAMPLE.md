# Counterparty Congestion Credit Report — SAMPLE

**Subject: Counterparty A** *(a real, active ERCOT CRR account holder; identity
redacted in this sample. All figures computed from public ERCOT data.)*
**Report date:** August 13, 2026 · **Prepared by:** Shadowprice
**Data:** ERCOT public CRR auction awards (48 auctions) and day-ahead
settlement prices (24+ months), engine-reconciled against actual ERCOT
settlement statements (91% of testable positions within 2%).

---

## 1. Summary credit view

Counterparty A carries one of the larger financial CRR books in ERCOT:
**22,501 MW across 15,867 live positions**, with delivery obligations running
to **December 2028**. Our mark on the forward book is **$56.8M**. Two findings
warrant credit attention:

1. **Realized performance is negative.** Over the 17 delivery months we can
   score (Sep 2024 – Jul 2026), the counterparty spent **$9.05M** in auction
   premium and realized **−$1.20M (−13.2%)**, against a market-wide average
   of **+1.0%**. Its win rate was 38% and losses came from both instrument
   types (options −$0.34M, obligations −$0.86M).
2. **Nearly a quarter of the forward book's value is stale-anchored.**
   **$13.5M of the $56.8M mark (23.8%, 5,289 MW)** sits on paths whose
   driving transmission constraints were re-rated or retired within the last
   90 days. Value histories on those paths predate the current grid; the
   realized outcome may differ materially in either direction.

A lender relying on this book as collateral support should treat the stated
mark as an upper band and weight the stale share separately.

## 2. Forward book

| Metric | Value |
|---|---|
| Live positions | 15,867 |
| Total MW | 22,501 |
| Delivery window | Jul 2026 – Dec 2028 |
| Shadowprice mark | $56.8M |
| — of which on recently-changed constraints | $13.5M (23.8%) |
| Longest-dated exposure | 29 months forward |

Concentration: the largest single path is 70 MW — the book is broadly
diversified by path (top-5 paths ≈ 1.4% of MW), which mitigates single-
constraint risk but ties the book's value to system-wide congestion levels
rather than idiosyncratic bets.

## 3. Realized track record (settlement-scored months)

| Period scored | Positions | Premium paid | Realized P&L | ROI | Win rate |
|---|---|---|---|---|---|
| Sep 2024 – Jul 2026 (17 months) | 14,459 | $9.05M | **−$1.20M** | **−13.2%** | 38% |

By instrument: options −$0.34M on $1.16M premium; obligations −$0.86M on
$7.89M. For reference, the whole market returned +1.0% on $637M over the
same months; obligation buyers as a class returned +22.3%. The counterparty
underperformed the market and its own instrument class.

## 4. What this report is and is not

- Every input is public ERCOT data; the subject's cooperation is not
  required and was not sought. Position data is published per account holder
  by ERCOT after each auction.
- Realized figures are settlement arithmetic — the same computation ERCOT
  itself performs — and our engine reproduces actual holder statements
  within 2% on 91% of independently tested positions.
- The forward mark is anchored on each path's realized payoff history in its
  delivery calendar months. It is **not a forecast**; magnitude uncertainty
  is material and disclosed, which is why the stale share is reported
  separately rather than silently trimmed.
- This sample is illustrative. A production report adds: month-by-month
  drawdown history, collateral-exposure trend vs. book value, position-level
  appendix, and quarterly re-issue with change tracking.

---

*Shadowprice values every ERCOT CRR book monthly from public data, with an
append-only audit trail: every report traceable to an immutable run ID,
engine version, and data snapshot. We hold no CRR positions and take no side
in any market outcome.*
