# Shadowprice — State of Play Brief (August 2026)

Context pack for reviewers. Everything below is built, measured, or sourced —
not aspiration. The venture: analytics/valuation for ERCOT Congestion Revenue
Rights (CRRs), aiming to become the "price of record" for an instrument that
has no marks, no venue, and no visibility between auctions.

## The market

- ERCOT CRRs: financial instruments paying DAM congestion on a source→sink
  path, per month, per time-of-use block. Options (floored) and Obligations
  (signed). Sold in monthly auctions + semi-annual long-term auctions up to
  3 years forward. ~$1.7–1.8B/yr auction revenue, growing 6–32%/yr.
- **285 active holders** with live forward positions (676,621 MW). Public
  award data names every holder's every position. 335 registered account
  holders with contact emails (public list).
- ERCOT holds **$6.86B collateral**; the CRR-driven component (TPES) is now
  the largest share. Collateral pressure = the exit motive.
- 2024 was a net-loss year for CRR holders as a class (−1.5%); 2025 +21%
  profitability rebound (market monitor).
- **No public bilateral trade data exists** (checked all 107 ERCOT API
  products; the 175-page State of the Market report never mentions bilateral
  trading). Transfers are possible through ERCOT's MUI (Section 23) but
  invisible. PJM's equivalent bulletin board does ~50–120 registered trades
  a year, mostly affiliates — the ISO-hosted venue model is empirically dead.
- Monthly auctions allow selling existing positions = the incumbent exit.

## What is built and deployed

1. **Data platform** (Supabase + Render + Vercel): 2+ years hourly nodal DAM
   prices; all 48 CRR auctions (awards per holder, clearing prices); 718k
   DAM binding-constraint hours w/ shadow prices; 148k RUC constraint rows;
   3.7 yrs resource outages. Live dashboard.
2. **Bid screen** (password-protected, live): prices every path against its
   delivery-calendar-month history, 50% margin rule, lottery sizing with
   liquidity caps, budget allocator, ERCOT-format CSV export. Tier logic now
   enforces the empirically-proven price zone (see finding #4).
3. **Marks engine + audit trail**: values every live position of every
   holder; append-only mark_runs/marks tables (DB-triggers forbid edits),
   engine git SHA + input watermarks per run. Target list ranks all holders
   by dollars sitting on stale constraints (top holder: $13.9M stale).
4. **Constraint intelligence**: registry (121 promotable constraints),
   novelty detector (re-rates: ~1/3 of active set re-rated within 90 days),
   empirical exposure map (node sensitivity to each constraint).
5. **Paper-trade rail**: immutable paper_bids table + two-phase scorer
   (cleared-vs-auction, then realized P&L). First test: a retiring 13-year
   CRR trader ("Steve") does a dummy bid for the SEP auction.
6. **Methodology document** (audit-grade, versioned, limitations disclosed).

## What is measured (the learnings)

1. **Direction is predictable, magnitude is not**: exposure-map sign
   agreement 96–97.9% out-of-sample; only 60.6% of magnitudes within 2×.
   Seven-plus predictive trading rules tested walk-forward: ALL FAILED.
   Standing rule: last 2 months always held out.
2. **Settlement reconciliation (ground truth)**: our computed payoffs match a
   real holder's actual ERCOT settlement statements within 2% on 91% of 602
   testable positions (2–7% on the rest; TOU holiday edge cases).
3. **Steve's book** (2,327 positions, 2024–27): +$48k on 2024 (~25% ROI on
   premium, 40% win rate), +$30.5k on 2025, −$1.3k 2026 YTD. Wins are cheap
   options sized big; losses are expensive options bought off last year's
   glory.
4. **Whole-market study (588,088 monthly BUY positions, 17 delivery
   months, $637M premium)**: market aggregate +1.0% ROI. By cleared price:
   +38% under $0.10, +16–21% at $0.10–0.50, +5.5% to $0.75, ~zero $0.75–5,
   **−13.3% above $5** (winner's curse). Win rates ~25–37% everywhere.
   **Options as a class LOSE −7.6% (−$34.5M); obligations WIN +22.3%
   (+$40.9M).** Nobody publishes these stats at monthly cadence (the market
   monitor publishes annually, ~18 months behind).
5. **Comps synthesis** (PE secondaries, pre-IPO, IRA tax credits, life
   settlements, cat bonds, pipeline capacity release, royalties, RECs):
   every activated secondary market required (a) transfer rails (ERCOT has),
   (b) a trusted pricing reference BEFORE volume (missing = our product),
   (c) a motivated-seller class (collateral relief; wind-downs),
   (d) concierge before platform. Realistic venue ceiling = cat-bond-like
   turnover (~8%/yr of outstanding → $150–400M/yr notional at maturity);
   at 10–50bps that's $0.1–1.5M/yr revenue — "a desk, not a company."
   **Conclusion: the pricing reference IS the business; the venue is the
   marketing story.**
6. **PJM scouting**: free API (nodal LMPs to 1998, constraint shadow prices
   to 2010), per-participant FTR awards public, $2.1B/yr auctions, 89% of
   FTR MW held by financial entities ($912M profit in 7 months). BUT monthly
   re-clears + FERC-mandated mark-to-auction credit = a free official mark
   partially fills our gap there; denser competition. Node locations
   workable via public GIS (unlike ERCOT's CEII lock).
7. Vendors (LCG/EnergyOnline — which Steve subscribes to — and NRGStream)
   sell backward-looking clearing data and forecasts; none publishes
   settlement-validated marks or monthly market P&L.

## The strategy on the table (see PRICE_OF_RECORD_STRATEGY.md)

Three publication layers: (1) free public monthly "ERCOT CRR Market
Scorecard" (the drumbeat; signature chart = ROI-by-price-bucket), (2) free
private per-holder book marks (outreach engine; paid detailed tier
$500–2k/mo), (3) paid attested audit marks (signed letters). Credibility
architecture: voluntary IOSCO-benchmark alignment — versioned methodology,
DB-enforced immutability, reproducibility from public data, published
SHA-256 of each run, disclosed error bars, no-prop-trading pledge.
Distribution: shadowprice.io + 335-holder email list + RTO Insider + ERCOT
stakeholder meetings. 90-day plan: 3 scorecard issues + paper-trade
self-scoring published win-or-lose. Expansion: NYISO likely #2; PJM via
analytics; CAISO under research.

## Candidate business lines (from earlier enumeration)

Recurring: audit marks ($500–2k/mo), constraint-change feed ($200–500/mo),
auction bid sheets ($250–1k/mo), collateral forecasting. Episodic: wind-down
mandates (%-of-notional), litigation/expert support. Leverage: white-label
to audit firms, buy-side advisory for data centers/miners entering ERCOT.
Long game: matching/marketplace fees, data API.

## Constraints & context

- Team: effectively a solo founder (Tim) + AI tooling + Steve as design
  partner/first user (retiring trader, account XSAAIC, 13 yrs). No outside
  capital raised for this venture; founder has parallel ventures.
- All input data is public; the engine is reproducible by a competent quant.
  The defensibility claims are: validation (needs a cooperating holder),
  the append-only track record (needs time), the contact list, and cadence.
- ERCOT is non-FERC (no federal benchmark regulation reaches it directly);
  a matching/brokerage business would need CFTC counsel before charging fees.
- Known open risks: single-holder validation, magnitude uncertainty
  disclosed, marks market size unproven (nobody has ever sold ERCOT CRR
  marks), email-outreach conversion unknown.
