# Pre-registration — the fade detector, graded on October

**Registered:** 2 Oct 2026, before October 2026 settles (2 of 31 delivery days
had posted; nobody looked at them for this). The git commit carrying this file
is the timestamp. Pushing it to the remote makes it externally visible.

**Rows:** [`2026-10-02-oct-fade-flags.csv`](2026-10-02-oct-fade-flags.csv)
(sha256 `11626140e468ebe01f261375519d5042cbd00ded02d9da13b31b32424459462e`).
That's all 408 positive-list (green and amber) rows of the published
`OCT2026Monthly` sheet. Each row carries `collapse_flag`, computed by
`strategy/valuation.py` as committed alongside this file, with the October
window: fit Oct 2024 plus Sep 2025–Jun 2026, and fade tail Jul–Aug 2026.

## What the rule is

A path is fading when its two most recent settled months each paid under
25% of its median fitted month. The rule was written after we saw the
NBOHR_RN and SHAMROCK_RN collapses (Jul–Sep 2026). Those paths are in this
set, so the rule was designed in-sample. This test is out-of-sample only
because **October's payouts are unseen**.

## Counts at registration

| | flagged | unflagged |
|---|---|---|
| filled (won at auction) | 34 | 24 |
| not filled | 162 | 188 |

## Predictions (graded from `sheet_snapshots` once the scorer posts October settlement)

**H1 (primary).** Among the 58 filled rows, the flagged group's return on
cost (`sum(realized) / sum(cost)`) is **lower** than the unflagged group's.

**H2 (secondary).** The flagged filled group's net P&L (`sum(pnl)`) is
**negative**.

Either outcome gets published on the method page and in the record, in the
same place and at the same size. If H1 fails, the collapse trigger is
withdrawn from the November-on sheets. It stays in only if the November
shadow test (below) passes.

## The November companion

The November market scan (`strategy/market_scan.py --target 2026-11`)
removes fading paths before the sheet is cut. Those rows are not discarded.
They get frozen as their own shadow sheet, `NOV2026Monthly-faded`, priced
exactly as they would have been without the detector. Then they're graded
beside the published `NOV2026Monthly`. Prediction: the faded shadow's filled
rows return less on cost than the published sheet's filled rows.

## Spike cap — descriptive only

The spike cap (the limit can never exceed the median month divided by 1.5)
changes the discovery book, which priced off the 12-month mean until now. In
October only 3 discovery rows had a limit that fewer than half their fitted
months beat. Two of them filled: both HKSN_SLR_ALL→ANCHOR_ALL blocks. Three
rows is too few to test, so no prediction is registered. The rows are marked
`spike_flag` in the CSV for the record.

## Addendum, same day: the November sheet is sealed

`NOV2026Monthly` was frozen in `sheet_snapshots` on 2 Oct 2026: 400 rows,
all amber. The removed rows were frozen as `NOV2026Monthly-faded`: 355 rows,
248 of them amber.

The as-published exhibit is **sealed**: its SHA-256 is
`94de57da6db39dabef5512dd54bc1d7d7c6b56ee7411ac86016ac9736adf1ea4`. The file
goes up on /record once the NOV bid window closes, and anyone can check it
against this hash.
