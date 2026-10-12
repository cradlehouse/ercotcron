# Shadowprice: Reconciled UI Review and Implementation Plan

Date: October 9, 2026. The NOV 2026 bid window opens Tue Oct 13 and closes Thu Oct 15 at 5pm Central. The DEC window opens Nov 3.

This plan reconciles two reviews:

- **Review A**: [ui-workflow-business-review-2026-10-09.md](ui-workflow-business-review-2026-10-09.md). Live testing as a comped member with an approved XSAAIC claim.
- **Review B**: a review in an earlier chat session, done from the code, the public pages, and production data. It looked at the trial member and the logged-out prospect.

The two cover different users. Review A saw a member whose sheet includes their own book rows. Review B looked at what a new trial member gets (only the 400 `Market` rows) and at the public pages that lead to sign-up. Combined, they show the whole funnel: prospect → trial → bid file → paying member.

## Status (Oct 9)

**Done:**
- Phase 1, all items (1.1–1.13).
- Phase 2: 2.1, 2.3, 2.4, 2.5, 2.6, 2.7.
- 2.2 in part: the dossier error now offers Retry and Back to the bid sheet.

**Still open:**
- Profiling `get_path_dossier`. This needs the path that timed out.
- 2.8: billing is a config switch, not code.
- Phase 3.

**Notes on what shipped:**
- The ticket was verified in a local harness: MW focus, reload persistence, hidden-selection notice, empty filter, and CSV holder plus row count.
- Member pages were not exercised signed in.
- The sign-in `?next=` applies to password sign-in only. The emailed magic link still lands on /app, because Supabase only honours redirect URLs on its allow-list.

## 1. Review A's findings checked against the code

Every finding in Review A that the code could confirm has a specific cause.

| Review A finding | Verdict | Cause |
| --- | --- | --- |
| Focus is lost while editing MW | **Agree, confirmed** | `Row` is a component declared inside `Ticket` ([ticket.tsx:156](../app/bids/ticket.tsx)). React sees a new component type on every render, so each keystroke unmounts and remounts every row. |
| Draft is lost after opening a path | **Agree, confirmed** | Selections and MW live only in `useState`, and path links navigate away in the same tab. |
| Hidden selections still export | **Agree, confirmed** | `selected` ignores the hedge filter ([ticket.tsx:97](../app/bids/ticket.tsx)). |
| "Worst case" is mislabelled | **Agree, confirmed** | [ticket.tsx:261](../app/bids/ticket.tsx) shows cost at the limit. An obligation can lose more than that. |
| Unchecked rows are hard to read | **Agree** | The whole row gets `opacity-45` ([ticket.tsx:160](../app/bids/ticket.tsx)). |
| Empty-filter crash (not reproduced live) | **Agree, confirmed in code** | `green[0] ?? amber[0]` ([ticket.tsx:305](../app/bids/ticket.tsx)) is guarded by `rows.length`, not by the filtered lists. "Obligations" on a sheet with no obligation rows crashes on `ex.tou`. |
| Dossier timeout shows a raw error | **Agree** | [path/page.tsx:53](../app/path/page.tsx) renders `error.message` with no retry and no way back. The slow query itself still needs profiling on the path that failed. |
| Circular "full method score" link | **Agree, confirmed** | `/app/method` returns data only to admins (`get_method_progress`) and sends members back to Track record ([record/page.tsx:67](../app/app/record/page.tsx)). |
| 0 MW shown with nonzero cost | **Agree, confirmed** | `Math.round(Number(r.mw))` ([book/page.tsx:141](../app/app/book/page.tsx), [:197](../app/app/book/page.tsx)). |
| 59 source rows vs 19 paths / 1,946 MW | **Not a defect, but needs a label** | 59 is the count of `Saaico 2027 First` valuation rows (43 with clearing history). My book aggregates holdings by path, with a `positions` count. The page should say "N positions across M paths" so the two numbers aren't confused. |
| Today leads with the Claim form | **Agree** | The same problem shows up in Review B: stale "October valuation run" and "September settlement" copy, and an alerts card for a feature that doesn't exist yet. |

### Where I disagree or would change the recommendation

1. **Save drafts in the browser, not on the server.** Review A says to save drafts "by account and auction" without saying where. Use `localStorage` keyed by auction and holder. A server-side table of draft bids would be a new store of bid intent. That cuts against the "your book data goes to you and nobody else" charter, and it adds a migration plus RLS work four days before a window. Revisit after DEC if members ask for drafts that follow them across devices.
2. **The export review should be a visible list, not a gate.** Agree that every exported row must be visible before download. Do that with an always-available "In this file (N)" list in the sticky bar, not a confirm step. Download stays one click.
3. **Keep Edge as the lead number.** Review A says big green edge percentages draw more attention than their caveats. Edge is the ranking signal and should stay prominent. The fix is consistent labelling: rename "Worst case", flag obligation risk on the row itself, and fold the dots legend into the column header. Making Edge smaller wouldn't fix the labels.
4. **Mobile and map come after the window.** Agree with both findings, but traders build bid files at a desk. Mobile matters for checking the book during the month, so it goes in phase 3.
5. **Measure with people, not analytics.** With a handful of members, a 30-minute session with the design partner per window tells us more than instrumenting time-to-draft. Don't build analytics yet.
6. **Passwordless sign-in is low priority.** It exists ("Email me a sign-in link"). Promote it only on invite links.

### Retracting part of Review B

Review B suggested **pre-selecting** the top market rows so a trial member's sheet doesn't open at "0 bids". The code deliberately keeps market-scan rows out of green ([page.tsx:158](../app/bids/page.tsx), from the July holdout). Pre-selecting them would quietly override a methodology rule under v1.3. Instead: an explicit **"Select top 25 by edge"** action the member clicks, plus an empty state in "Verified value" that explains why it's empty. The default stays the same for everyone and the rule stays intact.

## 2. What Review B adds that Review A could not see

Review A's account was comped and held XSAAIC, so these were invisible to it:

- **A trial member's sheet opens with nothing selected.** All 400 `Market` rows are amber and unchecked, "Verified value" is empty, and **Download bid file (0)** is disabled. (Confirmed from production `path_valuations`: `Market` 400 rows, `Saaico 2027 First` 59.)
- **The CSV's Account Holder is blank for every code except XSAAIC.** `ownedHolder` only searches the hard-coded `BOOK_HOLDER` map ([page.tsx:91](../app/bids/page.tsx)). Any other approved claim, or no claim at all, gives `,,,SOURCE,…`. Review A never tested CSV content.
- **Billing is off.** Trial and lapsed members see "Email us to subscribe".
- **Funnel gaps:**
  - The landing page never shows a sheet row.
  - /record lists exhibits but shows no graded outcome.
  - Logged-out visitors on /record see the members-only nav.
  - The sign-in redirect drops the page the visitor was trying to reach.
- **Stale copy outside Today:** the ticket's honesty note ("this September's settlement"), the landing page, and the strip page ("2028 strip sheet", "← September bid sheet").

## 3. Constraint for anything shipped during the window

NOV 2026 is sealed and pre-registered under methodology v1.3. Changes deployed between now and Oct 15 must be **presentation only**: no change to ceilings, tiers, default MW, or which rows appear. Everything in phase 1 meets that. The shortlist button selects rows but changes no values.

## 4. Implementation plan

### Phase 1: the bid workflow (ship by Mon Oct 12)

All in [app/bids/ticket.tsx](../app/bids/ticket.tsx) unless noted.

| # | Change | Detail | Source |
| --- | --- | --- | --- |
| 1.1 | Stable MW inputs | Replace `<Row r={r} />` with a plain render function (`{green.map(renderRow)}`, key on `<tr>`), or hoist `Row` to module scope with props. | A |
| 1.2 | Draft persistence | Save `{checked, qty}` to `localStorage` under `sp-draft:<auction.name>:<holder>`. Restore on mount, ignoring keys for rows no longer on the sheet. Wrap reads and writes in try/catch. Add a "Reset to defaults" link. | A |
| 1.3 | Path links open in a new tab | `target="_blank" rel="noopener"` on the path link. With 1.2, research never costs the draft. | A + new |
| 1.4 | Hidden selections | Add a **Selected** option to the filter. The sticky bar shows "N selected not shown". | A |
| 1.5 | "In this file" list | A collapsible list in the sticky bar of every row that will export: path, TOU, hedge, MW, limit. Download stays one click. | A (modified) |
| 1.6 | Empty-filter guard | Build the "how to read a row" example from the filtered lists, and show an empty state when a filter matches nothing. | A |
| 1.7 | Account holder in the CSV | In [bids/page.tsx](../app/bids/page.tsx), take the holder from any approved claim. Show a picker if there are several. With no claim, show a required "Your CRR account code" field in the sticky bar (saved locally) before download is enabled. | B |
| 1.8 | Shortlist for market-only sheets | A "Select top 25 by edge" button: liquidity first, then edge, the same as `byEv`. When there are no green rows, show an empty state in "Verified value" explaining that market-scan rows are never pre-verified. | B (revised) |
| 1.9 | Labels | "Worst case" → "Cost at your limit". "max at ceilings" → "cost at your limits". OBL rows get an inline "can lose more than this" note. Update the example paragraph to match. | A |
| 1.10 | Readable unchecked rows | Remove `opacity-45`. Mark selected rows with a left accent border instead. | A |
| 1.11 | Collapse the explainer after the first visit | `<details open>` in [bids/page.tsx:219](../app/bids/page.tsx): open only when a `localStorage` flag is absent. | A + B |
| 1.12 | Search box | Filter by source/sink substring. Cheap to build, and it makes 400 rows usable. | A |
| 1.13 | Stale copy | Ticket honesty note, Today (`October valuation run`, `September settlement`), strip page header and back link. Derive dates from `lib/auction.ts` or remove them. | A + B |

How to check it works: run `npx tsc --noEmit`, then in the dev preview as a member:

- Type "12" into MW and check focus stays.
- Change a selection, open a path, come back, and confirm the draft is intact.
- Filter to Obligations on a sheet with none: no crash.
- Select an obligation, switch to Options, and confirm the hidden count shows.
- Download, open the CSV, and check the holder column and the row count match "In this file".

### Phase 2: after the window closes, before DEC opens (Oct 16 – Nov 2)

| # | Change | Source |
| --- | --- | --- |
| 2.1 | **Today reorder.** Lead with the auction state card (phase, days left, sheet ready, "draft: N bids" from 1.2). Collapse the claim form to an "Account" line once a claim is approved. Link the Track record card. Label alerts "Coming". | A + B |
| 2.2 | **Dossier recovery.** Friendly error with Retry and Back to sheet. Profile `get_path_dossier` (`EXPLAIN ANALYZE`) on the path that timed out. We need that path's name from Review A's tester. | A |
| 2.3 | **Method-score link.** Hide it for non-admins and show "Full scorecard: publishes after NOV settlement", or open a member view of `get_method_progress`. Decide which. | A |
| 2.4 | **Book.** Show fractional MW (one decimal under 10, never 0 when nonzero). De-duplicate and translate warning codes, with details on demand. Header: "N positions across M paths". | A |
| 2.5 | **Public /record.** Add a one-line graded result per unsealed exhibit (OCT first). Give logged-out visitors the public nav with "Start free trial". Unseal NOV on Oct 15 after 5pm, as pre-registered. | B |
| 2.6 | **Sign-in return path.** Add `?next=` from `MemberGate` and honour it after sign-in, magic link, and sign-up confirmation (same-origin paths only). | B |
| 2.7 | **Landing.** Show one static sample row taken from an **unsealed** exhibit (OCT), never from the live NOV sheet. Fix the stale "September" copy. Label alerts as upcoming. | B |
| 2.8 | **Billing.** Turn on `NEXT_PUBLIC_BILLING_ENABLED` once Stripe keys exist. This is your business decision, with no code work beyond configuration. | B |

### Phase 3: later

- Mobile book summary at 390px: path, MW, result, and status together.
- Map → path → back to the draft as one investigation loop.
- Server-side drafts, only if members ask for them across devices.
- A moderated session with the design partner each window, using Review A's acceptance criteria as the script.

## 5. Acceptance criteria (Review A's list, plus additions)

Review A's criteria stand. Add these:

- The downloaded CSV's Account Holder is never blank. The download stays disabled until a holder code is known.
- A trial member with no claim can reach a non-empty file in at most two actions: shortlist, then download.
- Everything deployed during a bid window is presentation-only. Ceilings, tiers, and default MW match what was sealed.
- No page shows a date or month that conflicts with `lib/auction.ts`.
