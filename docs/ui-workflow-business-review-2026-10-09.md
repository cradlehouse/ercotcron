# Shadowprice: UI, Workflow, and Business-Fit Review

Date: October 9, 2026

## Assessment

Shadowprice contains useful analysis and a credible commitment to showing its results. The customer experience does not yet make that value easy enough to find, inspect, and carry through to a reviewed bid file. The most important improvements are workflow reliability and clearer presentation of decision-critical information.

The business need is practical: help an ERCOT CRR participant understand existing exposure, inspect valuation evidence, prepare a bid sheet, and judge the product's results. A customer paying the advertised $250 per month should be able to complete those tasks without losing work, interpreting raw system errors, or searching through unrelated candidates.

## Review Scope and Evidence

The review combined repository inspection with live use of shadowprice.io as a comped, non-admin member with approved access to account XSAAIC. Terms were accepted with the user's explicit confirmation.

Live coverage included onboarding, Today, the monthly bid sheet, hedge filters, quantity editing, a path drill-down, My book, a running-month daily chart, Track record, the full-method-score link, and the map. The book was also inspected at a 390px mobile viewport.

The user reported 59 source book rows. The live My book page displayed 19 paths and 1,946 MW. These are different presentations; this review did not reconcile their aggregation or verify financial calculations. Performance figures below describe what the UI displayed, not independently audited investment results.

No bids were submitted, no payment was made, and no application code was changed. Temporary bid selection and quantity edits reset when returning from path detail. The empty-filter crash identified in source was not reproduced with the live dataset.

## Wins

| Win | Observed evidence | Business value |
| --- | --- | --- |
| Clear product purpose | The product connects path value, historical clearing, quantities, and bid-file export. | Aligns with a concrete auction-preparation task. |
| Appropriate visual restraint | Compact navigation, tabular figures, restrained surfaces, limited accent colors. | Fits repeated professional use and numerical comparison. |
| Useful selection summary | Selected count and aggregate costs update when a row is selected. | Makes the impact of draft choices visible. |
| Account access works | XSAAIC appeared approved; member book and bid sheet loaded. | Demonstrates the core claimed-account experience. |
| Running-month evidence | The book showed paid-in, paid-out, pace, and an expandable daily chart that loaded successfully. | Supports monitoring between auction and final settlement. |
| Visible misses and losses | Track record included filled and missed paper bids, negative results, and partial-month labeling. | Supports trust through inspectable outcomes. |
| Geographic context | The map rendered live paths, scope controls, a month selector, and a data date. | Offers another way to investigate relationships. |

## Losses and Friction

Priority meanings: P1 blocks or materially compromises a core task; P2 creates avoidable confusion, effort, or loss of confidence.

| Priority | Finding and evidence | Customer/business consequence | Recommended change |
| --- | --- | --- | --- |
| P1 | Draft loss reproduced: select a bid, change MW from 1 to 12, open its path, return; selection becomes zero and MW returns to 1. | Research destroys preparation work and increases re-entry mistakes. | Save draft state by account and auction; restore it after navigation and reload. |
| P1 | Hidden selection reproduced: select an obligation, switch to Options; download remains enabled for the hidden obligation. | Export intent is unclear because the visible table no longer describes the selected file. | Show hidden-selection counts and a Selected view; review all exported rows before download. |
| P1 | MW editing reproduced: changing quantity moved keyboard focus to the page body. | Repeated keyboard entry is unreliable. | Stabilize row component identity and preserve focus through updates. |
| P1 | One path drill-down ended with "canceling statement due to statement timeout." | The user cannot inspect supporting evidence and has no local recovery control. | Address query latency; show a useful error with Retry and Return to draft. |
| P1 | The column labeled "Worst case" shows cost at the bid ceiling, while the page itself says obligations can settle beyond the premium. | A decision-critical label communicates a broader bound than the calculation represents. | Rename to "Cost at bid limit" and present obligation exposure beside the relevant totals. |
| P2 | Track record's "full method score" link led to a message directing the user back to Track record. | The promised evidence is unavailable through a circular journey. | Deliver the scorecard or clearly label its pending state at the original link. |
| P2 | Initial desktop bid view contains extensive explanation but no actual path rows. | Returning users must navigate past prose before starting work. | Collapse detailed guidance and put auction state, filters, and rows first. |
| P2 | Unchecked rows are dimmed, including numbers and warnings. | Available candidates resemble disabled controls and are difficult to assess. | Keep text readable; use selection controls and subtle row treatment for state. |
| P2 | Market candidates dominate the sheet; there is no dedicated existing-book filter. | The account-specific value is hard to locate. | Add My existing paths, Market candidates, and Selected views with counts and search. |
| P2 | Today prominently displays an account Claim form despite approved access. | Administrative setup displaces the customer's next task. | Lead with auction readiness, draft status, and flagged positions; move account management lower. |
| P2 | Mobile book tables place costs and returns offscreen; the daily chart also requires horizontal context. | Users cannot assess a position from the initial mobile view. | Show path, quantity, result, and status together in a compact mobile presentation. |
| P2 | A book row displays 0 MW alongside nonzero cost and payout; warnings contain repeated constraint codes. | Display precision and raw diagnostic text weaken confidence. | Preserve meaningful fractional MW and translate/deduplicate warnings, retaining details on demand. |
| P2 | Home copy says the sheet is forthcoming while the sheet is available; alerts are marketed publicly but described as still being wired inside. | Product readiness is ambiguous. | Drive availability labels from actual status and distinguish upcoming capabilities. |

## Ease of Use by Business Task

| Customer task | Assessment | Main friction | Desired experience |
| --- | --- | --- | --- |
| Enter an invited account | Moderate | Passwordless entry is subordinate to the password form. | A clear email-link sign-in route for invited users. |
| Know what to do today | Weak | Plan/account setup and product descriptions lead the screen. | Auction status and one clear next action, followed by account-specific exceptions. |
| Review existing exposure | Moderate | Book loads, but grades can be unscored, warnings are terse, and mobile outcomes are offscreen. | Explain coverage and show the most consequential flags with supporting evidence. |
| Prepare a bid draft | Weak | Lost state, focus loss, and hidden selections interrupt preparation. | Persistent edits, stable inputs, and a complete selected-bid review. |
| Investigate a candidate | Weak in the tested path | The sampled dossier timed out. | Evidence loads predictably or fails with recovery while preserving the draft. |
| Monitor the current month | Promising | Useful chart and running figures, but compact labels and precision need work. | Clear partial-period results, dates, quantities, and drill-down. |
| Judge the product's record | Moderate | Visible paper results help; the full-method link does not deliver its promise. | Clear separation of published sheets, model picks, running outcomes, and final scores. |

## Fit to the Business Need

### 1. Auction preparation should be the primary journey

Recommended sequence: choose auction -> inspect existing paths and candidates -> edit a saved draft -> review all selected bids -> export.

The export review should show account, auction, delivery period, instrument type, path, MW, limit, selected count, and aggregate cost at limits. Hidden rows must not disappear from this review. This is a workflow checkpoint, not a requirement to add repeated confirmation dialogs.

### 2. Account-specific information should earn its screen space

Today should answer: Is the sheet ready? What draft exists? Which positions need attention? What changed since the last visit? An approved holder should reach relevant book rows directly. Explanations of products belong behind those tasks rather than ahead of them.

### 3. Trust should come from consistent labels and accessible evidence

Large green edge percentages currently command more attention than their qualifications. Keep historical performance, data coverage, liquidity, and instrument risk distinguishable. Make data dates and score status readable. Avoid using a small disclaimer to correct a stronger headline or column label.

The record is a strength worth developing: keep missed bids and losses visible, and clearly distinguish reconstruction, paper fills, running settlement, and final results. The customer should not need to infer which kind of evidence a number represents.

### 4. The map should support a specific investigation

The rendered map provides context, but its contribution to the core task should be explicit through interactions: select a path, see its relevant evidence, and return to the same draft. Assess usefulness by whether customers complete an investigation, not by the visual alone.

## Recommended Delivery Order

1. Repair core preparation: preserve draft state, stabilize MW editing, surface hidden selections, and add a selected-bid review.
2. Repair evidence access: resolve the sampled path timeout, provide recovery states, and remove the circular scorecard journey.
3. Improve decision clarity: rename cost-at-limit labels, remove row-wide dimming, improve small text, and preserve fractional quantities.
4. Reorganize Today and the sheet around existing holdings, current auction status, and saved work.
5. Add the mobile summary presentation and reconcile availability/date copy across the product.

## Acceptance Criteria

- Changing a quantity keeps keyboard focus and supports uninterrupted multi-digit entry.
- Selected bids and quantities survive path navigation, Back, and reload for the same account and auction.
- Changing a filter clearly identifies hidden selections; the review lists every row that will export.
- A failed dossier offers Retry and Return to draft without exposing a raw database message.
- Cost-at-limit wording is consistent across rows, totals, examples, and export review.
- A scorecard link leads to a scorecard or an explicit pending state, without sending users in a circle.
- At 390px width, the initial position summary includes identity, quantity, outcome, and status together.
- Fractional holdings do not display as zero when they carry nonzero exposure.
- Approved members see their next working action before account-management forms.

## How to Measure Improvement

Establish a baseline before claiming gains. Measure time to prepare a reviewed draft, successful return from path research, input corrections, dossier error rate, and abandoned exports. In moderated testing, ask users to identify all selected bids after filtering and explain what the cost-at-limit number does and does not mean.

For business fit, observe whether a new member can find their own positions, inspect a flag, prepare a draft, and locate the relevant performance evidence without assistance. These measures are closer to product value than page views or time spent on the map. This review did not measure conversion, retention, or revenue impact.

## Remaining Verification

CSV content and submission were not tested. Billing was not exercised because the review account is comped. Authentication recovery, all empty states, keyboard/screen-reader coverage, and every responsive page remain outside the completed live checks. The source-level empty-filter failure needs a controlled reproduction. Financial calculations, source-row reconciliation, and the accuracy of published performance claims require separate data validation.
