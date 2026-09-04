# Nine-Seat Review — Consolidated Punch List (2026-09-03)

Nine independent reviews ran against the live site, repo, and production DB:
cold-eyes trader, numbers-skeptic quant, credit banker, security adversary,
data-integrity auditor, plain-language editor, legal (pre-counsel
issue-spotting), ad/growth, PR/comms. ~90 findings, deduped below, ranked.
Tags: (B) Bidder, (V) Valuer.

Verdicts in one line each:
- **Trader:** starts the trial, does not convert — bones worth $250/mo, trust wrapper worth $0 today.
- **Quant:** "fixable shop, not a fraudulent one" — trust direction and rejections, not any displayed magnitude, until one auction is self-scored end-to-end from platform data.
- **Banker:** real, differentiated asset; deliverable today is a hand-built PDF the schema can't reproduce. $2–5k/counterparty/quarter or $25–60k/yr desk seat once fixed.
- **Security:** the door has controls; the wall was missing (world-readable tables).
- **Data:** the honesty rail can currently neither detect its own dead jobs nor score its own bids.
- **Copy:** one artifact, five names; worst paragraph = strip discipline text.
- **Legal:** the "no personalized advice" line and the "Size the book for me" button cannot both go to counsel unexamined.
- **Ad:** zero analytics; the aha moment is unavailable ~25 days a month.
- **PR:** never let a participant learn we analyzed them before they chose to look.

## Already fixed during the review (live)

- claim_holder returned the verification token + unmasked registered email to
  any authenticated caller (self-approval of any holder code). Token now
  released only to the server secret. Verified both paths live.
- Re-claim downgraded approved → pending (lexical greatest()). Approved sticks.
- Unknown registry codes were accepted as "pending manual review" → rejected
  with instructions.
- Basic-auth prompts on member menu clicks; favicon/email-logo 401s; 13px
  monospace sitewide; double header; raw template literal on the ticket;
  map oversize; signup dead-end state; strip closed-state labeling.

## P0 — before any cold email goes out or any card is charged

1. **Lock down `path_valuations` (+ scan tables) from the anon key.** (B,V)
   The paid product is downloadable free via PostgREST today (`using(true)`
   RLS). Awards/offers/bids are public ERCOT data — leaving them readable is
   defensible; the valuations are not. Serve /bids & /map data through
   definer functions checking auth + plan; client gate stays as UX only.
   [security #1/#6]
2. **Restore nodal DAM ingestion + fix `is_settled`.** (B,V) Nodal dam_spp
   stopped 2026-08-01 (15 hub points/day since); every live paper-bid path is
   nodal → the self-scoring rail cannot score at all, and the >1000-row
   settled test would freeze partial-month P&L. Score only after month-end
   data for both endpoints; re-score until complete; also requeue all-miss
   batches so realized_value fills (counterfactual ledger currently omits
   them — flatters the record). [quant #1/#7, data #5]
3. **Wire the heartbeats + overdue-job check.** (B,V) `products` job dead
   since Aug 29 — invisible: /health returns ok, map shows "live". Env vars
   exist, plumbing built, all commented out. Add per-job overdue check to
   /health. One config task kills the whole silent-death class. [data #1]
   → Tim: set HEARTBEAT_URL_* on Render (healthchecks.io free).
4. **EV% must come from the September-conditioned `typical`, not annual
   `worth`.** (B) Our own holdout says worth pays ~10% of itself; trims cut
   the ceiling but never the headline EV. Cap/suppress EV on sub-25¢ clears
   (penny denominators). [quant #2]
5. **Stop shipping XSAAIC (and "Steve's book") to every user.** (B,V) Holder
   code comes from the signed-in user's approved claim or is blank with a
   prompt; map scope label → "My book"; auction meta moves from hardcoded
   constants to an artifact the cron updates. [trader #6, ad #7, copy #6]
6. **Reconcile the 96% / "self-scored in public" claims.** (B,V) 96% is the
   exposure-map's sign accuracy, not sheet accuracy — say exactly that
   everywhere it appears; "self-scored in public" is false until a scorecard
   URL exists. Publish the ungated scored-August sample (also the ad seat's
   #1 content ask) or soften the claim. [quant #5, legal #8, trader #2, ad #3]
7. **Methodology/code drift.** (V) MARK_METHODOLOGY line 5 says "suitable for
   financial reporting support" — Terms §3 says the opposite; delete the
   phrase (version bump). §3 conditioning + clearing-basis rules are not what
   valuation_screen.py ships; implement or annotate. Holdout is 4–6 weeks in
   practice, not "2 months always" — cut at today−2mo exactly. [legal #6,
   quant #3/#4]
8. **Confirm-by-GET → confirm page with a button.** (V) Mail scanners
   prefetch links and silently approve claims. Verify link lands on a page;
   POST confirms; email names the claimant; log IP/UA. Add per-IP/user rate
   limits on /api/claim + /api/verify-holder (holder/email enumeration).
   Revoke table grants on crrah_registry/holder_verifications
   (belt-and-suspenders). Security headers incl. Referrer-Policy:
   no-referrer. [legal #3, security #3/#5/#7/#8]
9. **"Size the book for me" needs a decision before counsel sees the brief.**
   (B) Budget-in → sized-MW-out is the strongest single fact against the
   impersonal-publisher posture. Options: (a) relabel as neutral calculator
   arithmetic + on-widget text, (b) drop margin-weighting (methodology says
   magnitude never sizes; the allocator uses marginX), (c) put it to counsel
   verbatim as new Question 6. Recommend (b)+(a) now, (c) regardless.
   [legal #4/#7, quant re methodology §7]
10. **2028 batch will never score under a guessed auction name.** (B)
    score_paper: alert when an open batch matches no ingested auction and a
    newer LT auction exists; reconcile names against MIS listing. [data #2]

## P1 — before/with the October push (sheet posts ~Sep 5, bids Sep 8–10)

11. **Dead-window mode.** (B) Between auctions, /bids leads with the scored
    prior sheet ("what we said / what cleared / what settled") — better proof
    than a dead ticket. Consider trial = "your next 2 auctions" instead of 30
    days. [ad #2, trader #5]
12. **Analytics.** (B,V) PostHog or Plausible + 5 events (landing_view,
    signup_submit, email_confirmed, bidsheet_open, csv_download). Activation
    metric: viewed a sheet within 24h of confirm. [ad #1]
13. **About page + neutrality pledge at the claim moment.** (B,V) Names,
    design-partner line, charter page, pledge sentence under the claim input.
    PR's about-page draft is ready in the PR review. [PR #2/#3, trader #8]
14. **/pricing page; unknown routes 404 instead of basic-auth challenge.**
    (B,V) [ad #4, trader #9]
15. **Copy pass.** (B,V) One name per thing (bid sheet / valuation run);
    define TOU/OPT/OBL/clearing price on first use per page; rewrite the "One
    rule" and strip-discipline paragraphs; OBL direction language ("a bad
    month takes money from you"); worst-case column mislabeled for OBLs (∞
    marker or p05-based); dots legend; CRRAH error message. Full replacement
    text sits in the copy review. [copy 1–12, quant #9]
16. **Freshness on every surface.** (B,V) computed_at/window_end on ticket,
    book, both map views (amber >2 days); "cached snapshot from {date}"
    banner when artifact fetch falls back to committed JSON; artifacts stamp
    {generated_at, run_id, data_through}. [data #3/#4/#8/#9/#10]
17. **Cold outreach format = PLAN.md 1.3 only.** (B,V) Tool + public record +
    claim invitation. Never send anyone their own positions/grades/stale
    flags uninvited; Scorecard is pull not push (no 335-contact blast);
    CAN-SPAM plumbing (postal address, opt-out, suppression list) before any
    list mail; retire PRICE_OF_RECORD_STRATEGY Layer-2 emails + "price of
    record" framing publicly. The ad seat's /h/{code} teaser page conflicts
    with this — resolution: the page may show public facts + claim CTA only,
    no grades, blurred or otherwise. [PR #1/#4/#5, legal #9/#10, ad #5]
18. **Scorecard editorial rules, published:** grade paths/prices never
    holders; ≥5-holder aggregation floor; issue #1 leads with our own paper
    misses. [PR #4]
19. **Billing (Stripe).** (B,V) Stripe Checkout + customer portal; ask at
    trial end, not signup (no-card trial stays). Trial-ending email (day 23)
    + in-app banner → Checkout link; webhook flips profiles.plan.
    → Tim: create the Stripe account + products ($250/$750), drop keys in
    Vercel env; integration is a day's build after that.
20. **Signup polish:** magic-link option, restate deliverables + next-auction
    date on /signup; og:image + per-page metadata for forwardability;
    "shadow price" definition line under the method section. [ad #6/#9/#10,
    PR #6]

## P2 — credit lane (deferred lane; fix before first pitch)

21. get_counterparty_book: remove/paginate the 500-row cap (biggest holders
    are 6.5–6.9k path groups — silently truncated), add control totals,
    dollar mark, realized P&L, stale-share, per-row computed_at. [banker #1/#9]
22. Exposure range (value_p05/p95 already in DB), tenor runoff table, 2–3
    stress scenarios. [banker #2]
23. margin_x must use the counterparty's own avg clearing price (same defect
    in get_my_book — grades a 3× overpayer "good"). [banker #3]
24. access_log: TRUNCATE guard, force RLS, grantee-readable view, log
    grant/revoke; grant history (one row per episode). [banker #4/#10]
25. mark_runs has 0 rows; stamp run ID + methodology version on reports.
    [banker #5]
26. Credit lane sells under an MSA, not the click-through ToS (§3 names
    "lender" in the no-reliance clause — unsignable by a bank). Second
    reconciliation counterparty. Remove/expand the credit-lane sentence in
    the privacy policy until the lane launches. [banker #6/#7, PR #10]

## Additions for docs/LAWYER_BRIEF.md (from legal seat)

- Q6: allocator + personalized holder views vs impersonal-publisher posture
  (CTA/IA; are CRRs "commodity interests" post-exemption?).
- Q7: uniform suggested limit prices distributed to horizontal competitors in
  one auction — information-sharing/antitrust check.
- Q8: CAN-SPAM review of registry-list outreach; confirm TCPA n/a; is
  "relevant correspondence" adequate disclosed basis for emailing non-users?
- Correct brief line 41: 96% describes exposure-map sign accuracy, not
  engine directional accuracy.

## Decisions needed (Tim)

- Allocator: relabel/de-magnitude now (recommended) or hold for counsel?
- Trial model: 30 days vs "next 2 auctions"?
- Repo: make private? (Schema + policies are public reading; defensible
  either way once RLS is real.)
- Stripe account + Render heartbeat URLs + (optional) CLAIM_RPC_SECRET env.
