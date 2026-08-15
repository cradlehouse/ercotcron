# Becoming the Price of Record for ERCOT CRRs

**Working name: Shadowprice. Version 1.0 — August 2026.**

The goal, in one sentence: when anyone — a holder, a CFO, an auditor, a
counterparty, a journalist — asks *"what is this CRR position worth?"*, the
answer they reach for is our number. Bloomberg for bonds, NAV for PE, dealer
sheets for cat bonds, Cruxtimate for tax credits. Nobody occupies this seat
for congestion rights, in ERCOT or anywhere else.

This document is the plan for taking the seat: what we publish, where, how we
prove we're honest, and the drumbeat that makes the number *the* number.

---

## 1. Why this seat is winnable by us, now

Every secondary-market comp we studied (PE, pre-IPO, tax credits, cat bonds)
activated only after a trusted pricing reference existed — and in several,
the reference outgrew the venue. The seat is empty in ERCOT because:

- ERCOT publishes auction clears but **no mark between auctions** and no
  forward value for multi-year books; the market monitor scores the market
  **once a year**, 18 months in arrears.
- Vendors (LCG/EnergyOnline, NRGStream) resell *backward-looking clearing
  data*; none publishes a settlement-validated valuation.
- We already hold the four assets a price of record requires:
  1. **The data**: 2+ years of nodal DAM prices, 48 auctions of clears,
     718k constraint-hours, every holder's positions.
  2. **A published methodology** (MARK_METHODOLOGY.md v1.0) with stated
     limitations — the thing a challenger must match before arguing.
  3. **Ground truth**: our marks reproduce a real holder's ERCOT settlement
     statements within 2% on 91% of testable rows. No competitor can claim
     this without a cooperating holder.
  4. **An enforcement-grade audit trail**: append-only mark runs, engine
     SHA + input watermarks per run, database triggers that physically
     reject edits. We don't promise we never restate — the schema forbids it.

## 2. What we publish (three layers)

**Layer 1 — free, public, monthly: the ERCOT CRR Market Scorecard.**
The drumbeat. Days after each delivery month settles (the market monitor
takes a year), we publish:
- whole-market monthly P&L: premium paid vs congestion paid out, win rate
- the ROI-by-price-bucket curve (this month vs trailing) — our signature
  chart; nobody else produces it
- OPT vs OBL scoreboard, top paying paths, constraints that made the month
- constraint-change bulletin: re-rates, retirements, new binders
No holder names in the public layer. Every issue states the run ID,
methodology version, and input watermarks it was struck from.

**Layer 2 — free, private, per-holder: your book, marked.**
The outreach engine (already built — target_list.csv ranks all 285 holders
by stale-flagged value). Each holder gets *their own positions* marked, with
trims and stale flags, referencing the same public run ID. Free first mark,
forever-free summary tier; the detailed per-position feed is the paid
product ($500–2k/mo by book size).

**Layer 3 — paid, attested: the audit mark.**
A signed valuation letter per holder per period — methodology version, run
ID, reviewer sign-off — for financial reporting support, collateral
disputes, wind-downs, and transactions. This is where the price of record
monetizes hardest per unit of work.

## 3. The authentication story ("we are recording this")

Modeled on what actually governs benchmarks — the IOSCO Principles for
Financial Benchmarks and PRA (price reporting agency) principles that
Platts/Argus live under. We adopt the substance voluntarily and say so:

1. **Published, versioned methodology.** Any change increments the version,
   with a changelog and rationale; a mark always cites the version it was
   struck under. (Done — MARK_METHODOLOGY.md.)
2. **Immutability by construction.** Marks are struck, never edited;
   corrections are new runs that reference the old. Database-enforced.
   (Done — mark_runs/marks triggers.)
3. **Reproducibility.** Every run records input watermarks (max ingested_at
   + row counts per source) and the engine git SHA. Given the same public
   ERCOT files, a third party can recompute any mark. All inputs are public
   data — nothing proprietary stands between a skeptic and verification.
4. **Tamper-evidence.** Each published Scorecard includes the SHA-256 of
   that run's marks file; the hash in a dated public publication proves the
   marks existed unaltered at that date. (Cheap, powerful, do from issue #1.)
5. **Validation disclosure.** The settlement-reconciliation result (91%
   within 2%) and the magnitude limitation (never used for sizing) stay in
   the methodology forever. A price of record that hides its error bars is
   asking to be dethroned by its first bad month.
6. **Conflict policy, stated early:** we do not trade ERCOT CRRs for our own
   account. The moment the marks desk has a book, the marks are dead. If a
   trading affiliate ever exists, it's separated and disclosed. (Platts rule
   #1; GreenHat is the cautionary tale everyone in this market remembers.)
7. **Complaints/challenge process.** A holder who disputes a mark gets a
   written response and, if we're wrong, a corrective run — logged in the
   same append-only record.

## 4. Where we publish

- **shadowprice.io** (register now): the Scorecard archive, the methodology,
  the run registry with hashes, and the per-holder login. The URL *is* the
  citation target.
- **Email**: monthly Scorecard to all 335 CRRAH contacts; per-holder marks
  to their own inbox. The list is the moat vendors don't have.
- **The trade press**: RTO Insider covers ERCOT stakeholder meetings weekly
  and is starved for data-driven stories; a monthly scorecard with a novel
  chart is an easy pitch. One citation = external authority.
- **ERCOT stakeholder process**: CMWG / WMS meetings take presentations;
  presenting the price-bucket curve or constraint-change data to the working
  group puts the name in ERCOT's own minutes.
- **LinkedIn**: each issue's signature chart, posted natively. The audience
  (energy traders, risk officers, auditors) actually lives there.

## 5. The drumbeat ("say it till everybody")

Benchmark status is a repetition game with a calendar:
- **Monthly**: Scorecard (settlement month closes → publish within days).
- **Auction cadence**: pre-auction bid-sheet note + post-auction "what
  cleared rich/cheap vs our marks" — twice-monthly touch in auction weeks,
  the second of which publicly scores our own prior note. Self-scoring in
  public is the fastest trust builder we have.
- **Event-driven**: constraint re-rate bulletins; a big miss month gets a
  "why the marks moved" note (owning misses is part of the record).
- **Annually**: a year-in-review that lands months before the market
  monitor's report and gets compared to it when the official one arrives.

Milestones that mark progress toward "of record": a holder forwards a mark
to their auditor → an auditor asks for the methodology → a counterparty
cites our mark in a transfer negotiation → the press quotes a number →
"per Shadowprice" appears in someone else's document without us in the room.

## 6. Sequencing (90 days)

1. **Now**: register shadowprice.io; Scorecard issue #1 from the market-P&L
   engine (data already computed: 588k positions, 17 months); Steve's paper
   trade runs as the first public self-scoring exercise.
2. **Days 1–30**: site up (Scorecard + methodology + run registry with
   hashes); first 20 stale-flag holder emails referencing issue #1.
3. **Days 30–60**: issue #2; RTO Insider pitch; first paid conversations
   from the free-mark responders; publish the SEP paper-trade clearing score.
4. **Days 60–90**: issue #3; October settlement scores the paper trade
   end-to-end — publish it, win or lose; CMWG presentation slot requested.
   By issue #3 the archive + hash registry *is* the track record.

## 7. Other markets (the franchise test)

The play ports wherever three conditions hold: (a) registered long-dated
congestion instrument, (b) no official between-auction mark, (c) public
enough data to compute one. Assessment so far:

| Market | Instrument | Data | Official mark? | Verdict |
|---|---|---|---|---|
| ERCOT | CRR | full (awards per holder) | none | **home market — run the play** |
| PJM | FTR | best-in-class API; per-participant awards | monthly BOPP re-clear + mark-to-auction credit | enter via analytics/bid sheets; marks wedge = illiquid paths & LT out-years |
| NYISO | TCC | good; reconfiguration auctions | auction cadence sparser than PJM | strong #2 candidate for the full play |
| CAISO | CRR | OASIS API | post-2018 reforms shrank the market | under research (agent report pending) |
| MISO / SPP / ISO-NE | FTR/TCR | moderate | sparse | fast-follow once the ERCOT template is proven |

Rule: don't enter market #2 until ERCOT has a paying marks subscriber and
three Scorecard issues in the archive. The franchise is the *format* +
*methodology* + *track record*; each new market reuses all three and only
rebuilds the data feed.

## 8. Risks, named

- **A bad public mark early.** Mitigation: publish error bars, self-score
  every month, own misses in writing. The record survives being wrong; it
  does not survive being edited.
- **ERCOT/IMM publishes the same stats.** Partial win for us (validates the
  need); our monthly cadence, per-holder layer, and audit product remain.
- **A vendor (LCG, Yes Energy) copies the Scorecard.** They lack the
  settlement validation and the append-only architecture; match our
  transparency or the copy reads as marketing.
- **Regulatory attention** (benchmark rules): voluntary IOSCO alignment is
  the answer and the moat — we *want* the standard raised to where we
  already stand.
- **The no-trading pledge costs us Steve-style P&L.** Yes. The pledge is
  the product. Paper trades and published scoring give us the intellectual
  P&L without the conflict.
