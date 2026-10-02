# State of Play — 2 Oct 2026

The September–October working record, written so a fresh session (or a fresh
person) can pick up without the chat that produced it. Everything here is
reproducible from the database, the migrations, and the scripts named below.
Older context: README.md (stack/jobs/routes), PLAN.md and
PRICE_OF_RECORD_STRATEGY.md (original thesis), LEGAL_REVIEW_2026-09.md +
LAWYER_BRIEF.md (compliance posture), MARK_METHODOLOGY.md.

## 0 · URGENT operational items (days, not weeks)

- **Every trial expires Oct 3–6** — and `has_active_plan()` now enforces
  plans INSIDE the member RPCs (migration 20260907080000). When a trial
  lapses, that user's product goes dark at the database. Steve
  (steven@saaicoenergy.com) expires **Oct 6**. Either comp him
  (`update profiles set plan='comp'`) or ship Stripe immediately. Tim = comp
  + admin already; test accounts will lapse harmlessly.
- **Stripe is not built.** It was deferred ("llc and stripe later", 5 Sep).
  The trial cliff makes it now.
- **Steve's Teams call** (he offered): walk his ERCOT upload flow; bring the
  deployment-book table. His last emails: bids were ERCOT-accepted (0 fills —
  outbid/no-market, verified), his Sept book reconciled to our panel within
  $10, and his structural complaint — "even when right I can't get money at
  risk" — is the product question the deployment book answers.

## 1 · What got built since the Sep 7 review (all live, all pushed)

- **Method page** (`/app/method`, admin = Tim + Steve): sheet tabs, three
  camp tiles (Won/Outbid/Said-no) with money + "X of N ahead" +
  "N backed by real buyers" lines, flow-field chart with color key and camp
  isolation, per-row daily charts, day→hourly drill-down bunched into TOU
  blocks (`get_path_day`). Members see only the member scorecard
  (`get_method_score`, shadow sheets excluded by `%shadow%` filter).
- **Admin page** (`/app/admin`): user list (email/plan/claims/terms/sign-in).
- **Public record** (`/record`): both as-published exhibits; middleware
  allowlists it.
- **Provenance**: `get_provenance()` + strip on every number-bearing page;
  marks.py logs runs to mark_runs.
- **Scoring standards** (the audit's product):
  - clearing price = non-`bid24hour` award rows only (Bid24Hour products
    blend TOU blocks); LT grading is delivery-window-matched (strip rows
    blend months). See memory `ercot-crr-award-file-semantics` and migration
    20260907100000.
  - **a fill is only CLAIMED with real buyers behind it** — `bought_mw` on
    every scored row; Won tile splits buyer-backed from price-test-only.
  - PREAWARD/STANDARD are BUY/SELL labels, NOT restatements (two wrong
    theories shipped and reverted same-day 7 Sep; `Phantom Clears` artifact
    is the audit narrative; negative_knowledge #24 holds the trap).
- **Raw auction archive**: all listed monthly+LT zips in the private
  `crr-raw` bucket (550MB, 24 files); every future auction auto-archives.
  ERCOT deletes the oldest monthly every month — this vault is the moat.
- **Secrets**: CLAIM_RPC_SECRET rotated and dedicated (Vercel + app_secrets
  match); Render has SUPABASE_URL/SERVICE_KEY; TRIGGER_SECRET in local .env
  matches Render.
- **Infra hygiene**: ruff-clean, 100 tests incl. Postgres security suite
  (tests/test_pg.py, rollback-transaction RPC tests), pre-push hook runs
  ruff+pytest+tsc.

## 2 · The experiment registry — what is frozen and what each one decides

All in `sheet_snapshots` (identity-immutable) unless noted. The scorer
grades them automatically; nothing needs a human until decision day.

| Experiment | Frozen | Question | Decided by |
|---|---|---|---|
| `OCT2026Monthly` (published, 1.5× rule) | Sep 6 | the public record | Oct 31 settlement |
| `OCT2026Monthly-shadow125` (1.25× limits) | Sep 7 | is the discipline cliff at 1.25×, not 1.5×? (Sep banding: 1.00–1.25× ran 168%, 1.25–1.5× ran 73%) | Oct 31 settlement |
| `NOV2026Monthly-hubshadow` (34 hub-leg paths, median-priced, fade-gated, market-sized) | Sep 24 | does the deployment book earn its depth out-of-sample? | NOV results (~Oct 17) + Nov settlement |
| `outage_predictions` table (5 claims, append-only guard) | Sep 7 | do outage node-maps predict? Headline: **CPSES_UNIT1 refuel due Oct 1–Nov 30** (18-mo clock; nuclear class validated 17–21/25 held-out) | when the outage tape shows it |
| Paper batches (SEP recon, OCT model, 2028 LT) | various | per-batch | ongoing |

**October results landed Sep 17** (auto): published sheet 59 fills/121
traded/290 never-traded (45 buyer-backed, 112 of 145 MW takeable); shadow125
76 fills; paper 5/15; Steve 0 fills (real, accepted bids at our limits —
outbid on 2, no market on 3). 86 October bid-sheet rows carry the Comanche
Peak outage-watch annotation (favorable AND unfavorable).

## 3 · Research results (reproducible; scripts in strategy/)

- **September final (published sheet, ~day 22)**: ladder intact and monotonic
  — Won 145% > Outbid 107% > Said-no 65%; concentration honest (10/41 ahead,
  carriers rotate); Steve's real book +$108 for Sept, reconciled to his own
  CSV within $10. Lifetime Steve: one PeakWE block carries the book (+$919).
- **Capacity map** (`where the money is`): hub/zone-leg paths = 2,600
  paths, ~$30.7M and 74,000 MW per monthly auction (a 25 MW order is
  invisible); minor-minor = $59M across 26k paths but ~nothing per path (290
  of 411 sheet picks never traded); one LT round = ~$1.9B notional. The
  disciplined minor-path game caps near $50–100k/mo; rung C (paying market
  on outbid paths) is $309k/mo at ~43¢/$ historical.
- **Ten-month walk-forward of the hub-leg screen**
  (`strategy/hub_walkforward.py`, DEC25–SEP26, decisions blind each month):
  ~$19k/mo deployed, **$187k in → $334k out, net +$147k (178%)** — but 5 of
  10 months lose and Jul+Aug made ~all of it (cheap-season entries, ordinary
  payouts). Sep-26 = 7%.
- **Two-year payout profile** (Oct24–Sep26, 203-path revealed portfolio):
  payouts are steady ($1–3/MWh) all year both years → **the edge is
  seasonal auction MISPRICING, not seasonal congestion**. April is the best
  payout month both years (= peak maintenance season, matches outage
  calendar). **Sep-26 is a regime break**: $0.15/MWh vs $1.54 in Sep-25 —
  10× below any month in 24; the West-congestion fade is structural-looking;
  the screen's fade gate is load-bearing (the ungated Sept rehearsal lost
  64%).
- **Outage studies** (`strategy/outage_study.py`): 58 units ≥300MW with
  inferable schedules; nuclear = 18-month clocks; outage node-maps predict
  held-out episodes for nuclear + MLSES_UNIT2 (20–24/25 sign agreement),
  lignite summer tests INVERT (negative_knowledge #24-adjacent, logged);
  season-matching helps some (OGSES_2: 7→18/25). `outage_node_deltas` +
  `node_day_spread` tables hold the maps. SCES_UNIT1 (769d) and MLSES_UNIT1
  are retirement-shaped, which rewires congestion permanently.
- **Crowding monitor** (results-day routine): Oct — our sheet paths cleared
  at median 1.26× their summer basis vs 1.03× for ~15k controls. With ≤1
  reader bidding this is selection, not impact; it is the dial to re-run
  every results day as users grow.

## 4 · Method fix queue (before the NOV scan builds a sheet)

1. **Spike-aware limit cap** — HKSN_SLR_ALL→ANCHOR_ALL proved the margin
   rule mean-chases on median-loser paths (10/12 losing months at our
   limit). The live rows carry a full warning; the rule itself still needs
   the median/spike cap. (The hub screen already prices off medians.)
2. **Fade detector** — the warnings system missed raw two-month payout
   collapses (NBOHR, SHAMROCK). Detector gets a payout-collapse trigger.
3. **Deployable-dollars view** — per-row "how much money actually fits"
   from bought_mw; "build me a $25k month" cut. Direct answer to Steve's
   complaint; data already captured.
4. CSV export nudge (Steve hand-typed his October file; the export is
   ERCOT-valid as-is — surface it harder).

## 5 · Business state (GTM inputs)

- **Users**: 7 accounts; real = Tim (admin), Steve (admin, trial→Oct 6, the
  design partner, SPFI affiliation stays private). Rest are test accounts.
  No sign-ins between auction days — usage follows the auction calendar.
- **Steve arc**: challenged data → audit held to the fourth decimal → his
  real bids graded exactly as the sheet predicted → his capital complaint
  became the deployment-book spec. Emails sent: audit findings, October
  examples + worked path explanations, correction note. DRAFT pending
  Tim-send: "Your capital problem — where the size fits" (walk-forward +
  November maintenance angle incl. CPSES refuel). Teams call offered by him.
- **Site has NO analytics** (auth logs only; access_log table exists,
  unwired). Standing offer: dogfood onion.js from The Onion.
- **Outreach**: warm-only; cold registry wave still gated (counsel Q8, about
  page, sending domain). Suppression/unsubscribe live and rotated.
- **Product shape emerging from the data**: two books —
  (a) the published minor-path sheet: high-%, low-capacity, lottery-shaped,
  pre-registered record = the trust engine;
  (b) the hub-leg deployment book: real dollars, 5-of-10 losing months,
  heat/maintenance-paid = the money answer (validating via NOV hubshadow).
  Plus the valuer lane (neutral-path portfolio, adjacent markets ranked in
  memory `shadowprice-review-2026-09`: basis scorecard, TCEQ credits,
  PJM/MISO, P&A liability).
- **Pricing**: $250/mo trial-first; no billing rail yet.

## 6 · Where things run

Vercel (web, auto-deploy on push) · Render (ingest+jobs, auto-deploy) ·
Supabase cqoswqnngrlxomufxzix (69+ migrations, RLS, definer RPCs) · local
.venv for research scripts (`strategy/`, env-driven paths via
strategy/common.py; market_scan too big for Render's 512MB). Preview:
launch config `ercotcron`, port 4420; test login viswise+uxwalk@gmail.com.
Pre-push hook enforces green. The chat that built all this ends here; the
record continues in the repo, the database, and the method page.
