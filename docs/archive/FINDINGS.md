# What the data actually says — regression sweep, 28 Jul 2026

Every number below is computed from the loaded history (24 months × 15 hub/zone
points, 12 CRR auctions, 4 days of weather-model data), locally, with
Benjamini-Hochberg correction where families of tests were run. Findings are
ranked by how actionable they are, and each carries its caveat inline.

---

## Tier 1 — survived correction, physically coherent, current

### F1. Day-ahead overprices the solar belly at south-central zones
**15 of 360 node-hour cells survive BH at FDR 5% over 24 months. All fifteen
are positive (DA > RT), and they cluster in HE12–15 at LZ_LCRA, LZ_CPS,
LZ_AEN, HB_SOUTH, HB_PAN** — the solar hours, at the solar-belt points:

```
LZ_LCRA HE14  +$2.80/MWh  t=4.3  hit 65%  (732 days)
LZ_CPS  HE14  +$2.56/MWh  t=4.0  hit 63%
LZ_LCRA HE15  +$3.03/MWh  t=4.0  hit 66%
LZ_CPS  HE19  +$5.14/MWh  t=3.3  hit 65%   ← evening ramp, biggest $
```

The story is physical, not statistical: day-ahead persistently fails to price
midday solar output at the zones where solar concentrates. The trade is selling
DA / buying RT in those specific cells. Caveat: hit rates are 60–66%, so this
is a portfolio edge, not a coin with two heads — and cell-level t of 4 is
strong but the 15 cells overlap heavily (same afternoons).

### F2. The West-zone basis has collapsed, now, and nothing explains it yet
For 24 months LZ_WEST priced ~$7/MWh **above** HB_WEST and ~$7 above the North
zones. In the last 30 days that premium has vanished:

```
HB_WEST−LZ_WEST   24mo −7.49   now −1.22   (0.71 sd dislocation)
HB_PAN −LZ_WEST   24mo −14.51  now −3.36   (0.71 sd)
```

Every one of the top eight dislocations involves LZ_WEST. Something structural
changed in far-west Texas in the last month — new transmission energised,
Permian load shift, a retired constraint. **This is the single most current
finding**: a live regime change the binding-constraints data should be able to
name once its backfill runs. For a CRR holder, paths into LZ_WEST bought at
historical levels are now mispriced against the new regime, in one direction
or the other depending on cause.

### F3. Battery arbitrage is being competed away, fast
Monthly gross for a 2-hour battery (top-2 minus bottom-2 hours, $/MW-day):

```
Aug 2024: $303 (hub) / $350 (LZ_WEST)
Aug 2025: $114 / $146
May–Jul 2026: $66–93 (hub) — roughly a THIRD of two summers ago
```

The compression is monotone and large. Anyone underwriting storage on
2024-vintage spread assumptions is buying yesterday's returns. Conversely the
spread that remains is increasingly concentrated in fewer, spikier days —
which favours operators with better day-selection (see F5).

## Tier 2 — real, but tempered by the fuller data

### F4. CRR option selling is path-selective, not a money printer
The earlier flagship (SOUTH→LZ_SOUTH options: 10/10 months, never lost) is
real but selected. **Pooled across all hub option paths**, the seller's keep
by delivery month:

```
Sep +0.55  Oct +2.50  Nov +1.86  Dec +1.18  Jan −0.91  Feb +0.67
Mar −0.45  Apr −0.69  May +0.33  Jun +0.82
```

Three losing months in ten, pre-summer, on the blanket portfolio. The edge
lives in *which* paths (28 BH survivors of 93), not in shorting everything.
And the professional behaviour still stands: the pros flip inventory for
+$0.35 rather than hold for the fatter, riskier keep.

### F5. The scarcity knee is not yet measurable from stored data
Net-load-forecast → price is monotone (p50 $15.6 → $35.3 across 10–55 GW) but
shows no knee — because the stored forecast sample spans only ~100 mild days.
The wind/solar/load "latest vintage" backfill kept the wrong vintage (bug
below), so the true 24-month curve is pending a re-backfill.

## Tier 3 — collecting, no verdict

### F6. Weather-model disagreement vs price movement: n=91 hours
corr −0.06, and high-disagreement hours moved *less* — the opposite of the
hypothesis, on four days of data. Meaningless either way at this n. The
collector runs hourly; this graduates in weeks.

---

## Bug found by the sweep (why "verify before build" was right)

**Every wind and solar `actual_mw` in the database is NULL.** The backfill's
"latest vintage wins" logic assumed oldest-first row order; the endpoint
returns newest-first, so it kept the *oldest* pre-delivery forecast for every
hour — which never contains an actual. Load history has the same flaw. The
wind-miss regression and true net-load curve are blocked until a re-backfill
with vintage selection by `posted_at`. Fix is written and held.

---

## UI proposal — built from the survivors, nothing else

1. **Solar-belly board (F1).** The 15 surviving cells as a live tile grid:
   today's DA price vs RT-so-far in each cell, cumulative P&L of the cell
   strategy, hit-rate tracker. One screen that answers "is the anomaly still
   paying, today?"

2. **Basis-break monitor (F2).** Each tracked pair's 30d basis vs its 24mo
   band; LZ_WEST panel pinned first while the dislocation stands. When
   constraints backfill lands, annotate with which constraint changed.

3. **Battery decay curve (F3).** Monthly arb value per point with the
   compression trend drawn — the chart a storage investor needs before
   believing any pro-forma.

4. **CRR path selector (F4).** The 28 surviving sell-paths with per-month keep
   and worst month; pooled-vs-selected comparison so the "not a money printer"
   caveat is visible in the same view.

The z-score scanner stays (it caught nothing false, and F1/F2 will surface in
it live), but these four lead — each one is a measured anomaly, not an
assumed one.

## Held for one approved deploy (nothing pushed)

1. `SET LOCAL statement_timeout` + `rt_hourly` pre-aggregate → makes the
   scanner matviews populate (root cause: every Supabase execution path has a
   statement ceiling; the query must get cheaper and the session must lift it).
2. Vintage-selection fix in `fundamentals._renewable` / `load_range`
   (compare `posted_at`, don't trust row order) → then wind/solar/load
   re-backfill (~5h, restartable).
3. RT all-points resume (95 windows remaining).
4. `/scanner` page reads the populated matviews as-is; the four boards above
   are new pages, built after sign-off on this document.
