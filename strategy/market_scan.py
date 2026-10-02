#!/usr/bin/env python3
"""Whole-market scan: value every path the CRR auctions have actually cleared.

    python strategy/market_scan.py --target 2026-11 [--dry-run]

Until now the valuation screen graded one trader's book (59 combos) plus a
shortlist from winning firms (11). This values the ENTIRE traded universe —
every distinct (source, sink, TOU, hedge) that cleared in any auction we hold —
against a year of day-ahead settlement, and keeps the verified mispricings.

Design constraints that shaped it:
  - DAM prices come from the LOCAL month caches, not the database. The
    instance died once this week under our scans; this touches Postgres only
    for the (small) award universe and the (capped) result write.
  - numpy does the arithmetic: an hours x points matrix, one vector op per
    path. Pure-Python loops over 50k paths x 7k hours would take hours;
    this takes minutes.
  - Output is CAPPED. The point is a shortlist of verified value, not a dump:
    top rows by margin with >= 2,000 priced hours and a 10c floor, written to
    path_valuations as book='Market'.
"""
from __future__ import annotations

import collections
import datetime as dt
import pathlib as _pl
import sys as _sys

_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import json
import os
import pathlib
import time

import numpy as np
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg

from strategy.common import CACHES, REF, dated_copy, load_ref
from strategy.valuation import value_months

# The window is derived from the delivery month being bid (--target YYYY-MM):
#   fit    the 10 months ending four months before delivery, plus the same
#          month two years back (its one-year-back twin sits inside the window)
#   tail   the two settled months between the window and the auction — HELD
#          OUT of the fit (house rule), read only by the fade detector, which
#          can remove a path but never price one (strategy/valuation.py)
# OCT 2026: fit oct24 + sep25..jun26, tail jul26..aug26.
# NOV 2026: fit nov24 + oct25..jul26, tail aug26..sep26.
MIN_HOURS = 2000
MATERIALITY = 0.10
CAP = 400          # rows written to the platform
_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _shift(y: int, m: int, k: int) -> tuple[int, int]:
    i = y * 12 + (m - 1) + k
    return i // 12, i % 12 + 1


def window(target: str) -> dict:
    """Month tags and labels for a delivery month 'YYYY-MM'."""
    y, m = (int(x) for x in target.split("-"))

    def tag(ym):
        return f"{_MON[ym[1] - 1]}{ym[0] % 100:02d}"

    def lab(ym):
        return f"{ym[0]}-{ym[1]:02d}"

    fit = [_shift(y, m, -24)] + [_shift(y, m, k) for k in range(-13, -3)]
    tail = [_shift(y, m, -3), _shift(y, m, -2)]
    return {
        "fit_tags": [tag(x) for x in fit], "tail_tags": [tag(x) for x in tail],
        "fit_months": [lab(x) for x in fit], "tail_months": [lab(x) for x in tail],
        "target_months": [lab(_shift(y, m, -24)), lab(_shift(y, m, -12))],
        "window_start": f"{lab(_shift(y, m, -13))}-01",
        "window_end": f"{lab(_shift(y, m, -3))}-01",
    }


from ercot.calendar import tou_of


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="delivery month being bid, YYYY-MM")
    ap.add_argument("--dry-run", action="store_true", help="value and report; write nothing")
    args = ap.parse_args()
    W = window(args.target)
    print(f"target {args.target}: fit {W['fit_tags']} | fade tail {W['tail_tags']}", flush=True)
    t0 = time.time()

    # ---- 1. price matrix from local caches
    print("loading cached DAM months...", flush=True)
    hour_keys: list[tuple[dt.date, int]] = []
    point_idx: dict[str, int] = {}
    cols: list[dict[int, float]] = []      # per hour: point index -> price
    for tag in W["fit_tags"] + W["tail_tags"]:
        path = next((d / f"dam_{tag}.json" for d in CACHES if (d / f"dam_{tag}.json").exists()), None)
        if path is None:
            # one bounded pull, then cached forever
            mon = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}[tag[:3]]
            yr = 2000 + int(tag[3:])
            lo = dt.date(yr, mon, 1); hi = dt.date(yr + (mon == 12), (mon % 12) + 1, 1)
            print(f"  {tag}: pulling from dam_spp ({lo}..{hi})...", flush=True)
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as cdb:
                cdb.execute("set statement_timeout='10min'")
                cur = cdb.cursor()
                cur.execute("""select settlement_point, delivery_date::text, hour_ending, price
                                 from dam_spp where delivery_date >= %s and delivery_date < %s""", (lo, hi))
                rows = [{"settlement_point": r[0], "delivery_date": r[1],
                         "hour_ending": r[2], "price": float(r[3])} for r in cur.fetchall()]
            (CACHES[0] / f"dam_{tag}.json").write_text(json.dumps(rows))
        else:
            rows = json.loads(path.read_text())
        by_hour: dict[tuple[str, int], dict[int, float]] = collections.defaultdict(dict)
        for r in rows:
            sp = r["settlement_point"]
            i = point_idx.setdefault(sp, len(point_idx))
            by_hour[(r["delivery_date"], r["hour_ending"])][i] = float(r["price"])
        for (dstr, he), prices in by_hour.items():
            hour_keys.append((dt.date.fromisoformat(dstr), he))
            cols.append(prices)
        print(f"  {tag}: +{len(by_hour):,} hours", flush=True)

    n_hours, n_points = len(hour_keys), len(point_idx)
    print(f"matrix {n_hours:,} hours x {n_points:,} points", flush=True)
    M = np.full((n_hours, n_points), np.nan, dtype=np.float32)
    for row_i, prices in enumerate(cols):
        for col_i, price in prices.items():
            M[row_i, col_i] = price
    tou_arr = np.array([tou_of(d, he) for d, he in hour_keys])
    masks = {t: tou_arr == t for t in ("Off-peak", "PeakWD", "PeakWE")}
    month_arr = np.array([d.strftime("%Y-%m") for d, _ in hour_keys])
    # valuation statistics see fitted hours only; the tail is fade evidence
    in_fit = np.isin(month_arr, W["fit_months"])
    masks = {t: m & in_fit for t, m in masks.items()}
    tail_masks = {t: (tou_arr == t) & ~in_fit for t in masks}

    # ---- 2. the traded universe, with what each combo actually cleared at
    print("fetching traded universe from crr_awards...", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        c.execute("set statement_timeout='30min'")
        cur = c.cursor()
        # Clearing basis = the RECENT monthly auctions only, and never a signed
        # average: OBL clears straddle zero (FERMI->AMISTAD ranged -15.94 to
        # +5.59), so an all-time mean nets to a tiny "cost" no auction ever
        # charged and margins explode against it.
        # Same semantics as the original ranked-window query (each path's own
        # 3 most recent monthly auctions form its clearing basis), but the
        # ranking happens in Python: the Micro tier cancelled the window
        # function at 10 minutes once the award table grew. Plain group-by,
        # server-side cursor so nothing materialises on the instance.
        agg: dict[tuple, list] = {}
        with c.cursor(name="universe_stream") as scur:
            scur.itersize = 20000
            scur.execute("""
                select source, sink, time_of_use, hedge_type, auction_name,
                       -- Bid24Hour products carry one blended price across TOU
                       -- blocks; a TOU's clear comes from single-block rows.
                       coalesce(avg(clearing_price) filter (where not bid24hour),
                                avg(clearing_price)) cp,
                       sum(mw) mw, max(ingested_at) ing
                  from crr_awards
                 where auction_name like '%%Monthly'
                 group by 1,2,3,4,5""")
            for s, k, t, h, _a, cp, mw, ing in scur:
                agg.setdefault((s, k, t, h), []).append((ing, float(cp), float(mw or 0)))
        universe = []
        for key, entries in agg.items():
            entries.sort(key=lambda e: e[0], reverse=True)
            cp3 = sum(e[1] for e in entries[:3]) / min(3, len(entries))
            universe.append((*key, cp3, len(entries), max(e[2] for e in entries)))
        # staleness flags for the confidence column
        exp = load_ref("constraint_exposure.json")
        cur.execute("select constraint_name, recent_rerate, possibly_retired from constraint_novelty")
        nov = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    stale_nodes: dict[str, str] = {}
    for cname, entries in exp.items():
        rr, ret = nov.get(cname, (False, False))
        if rr or ret:
            for e in entries:
                if abs(e["beta"]) >= 0.02:
                    stale_nodes.setdefault(e["node"], cname)
    print(f"universe: {len(universe):,} distinct path/TOU/hedge combos", flush=True)

    # ---- 3. value each combo
    results, faded = [], []
    skipped_pts = skipped_hours = 0
    for i, (src, snk, tou, hedge, cleared, n_auc, mw) in enumerate(universe):
        si, ki = point_idx.get(src), point_idx.get(snk)
        if si is None or ki is None or tou not in masks:
            skipped_pts += 1
            continue
        diff = M[masks[tou], ki] - M[masks[tou], si]
        diff = diff[~np.isnan(diff)]
        if diff.size < MIN_HOURS:
            skipped_hours += 1
            continue
        if hedge == "OPT":
            pay = np.maximum(diff, 0.0)
        else:
            pay = diff
        worth = float(pay.mean())
        med = float(np.median(pay))
        # A 12-month mean is carried by its worst winter week: on the July
        # holdout the median pick paid ~10% of its annual-mean "worth". For a
        # MONTHLY product the honest base is the typical month — the median of
        # the per-month means — which a single January cannot drag.
        mmask = month_arr[masks[tou]][~np.isnan(M[masks[tou], ki] - M[masks[tou], si])]
        permonth = {m: float(pay[mmask == m].mean()) for m in W["fit_months"] if (mmask == m).sum() >= 100}
        tdiff = M[tail_masks[tou], ki] - M[tail_masks[tou], si]
        tmonths = month_arr[tail_masks[tou]]
        tpay = np.maximum(tdiff, 0.0) if hedge == "OPT" else tdiff
        tail = [float(np.nanmean(tpay[tmonths == m])) for m in W["tail_months"]
                if (~np.isnan(tdiff[tmonths == m])).sum() >= 100]
        target = [permonth[m] for m in W["target_months"] if m in permonth]
        # The typical month (median of monthly means), never the 12-month mean,
        # capped by the recent months and by past payouts of the target month;
        # fading = recent decay OR a two-month payout collapse in the held-out
        # tail. One rule for every scan: strategy/valuation.py.
        v = value_months(list(permonth.values()), tail, target)
        if v is None:
            continue
        typical, fading = v.typical, v.fading
        cleared_f = float(cleared or 0)
        trim, why = 0.0, []
        s = stale_nodes.get(src) or stale_nodes.get(snk)
        if s:
            trim += 0.30
            why.append(f"{s}: re-rated <90d")
        if med > 0 and worth > 3 * med:
            trim += 0.25
            why.append("spike-driven")
        elif any(r.startswith("spike") for r in v.reasons):
            why.append("spike-driven")
        ceiling = typical * (1 - min(trim, 0.75))
        # Near-zero clearing prices make margin ratios explode into nonsense
        # (a $4 path over a $0.00 clear is "1600x"), and one-auction paths are
        # a single observation. Floors: the auction must have priced it at
        # least a nickel, across >= 3 auctions, and the absolute gap must be
        # worth collecting, not just the ratio.
        if ceiling < MATERIALITY or cleared_f < 0.05 or int(n_auc) < 3:
            continue
        margin = ceiling / cleared_f
        if margin <= 1.25 or (ceiling - cleared_f) < 0.10:
            continue
        # Removed by the fade detector: kept aside with the reason, so the
        # removals are frozen as their own shadow sheet and graded too.
        (faded if fading else results).append({
            "source": src, "sink": snk, "tou": tou, "hedge": hedge,
            "worth": round(worth, 4), "median": round(med, 4),
            "p05": round(float(np.percentile(pay, 5)), 3),
            "p95": round(float(np.percentile(pay, 95)), 3),
            "pct_pos": round(float((pay > 0).mean() * 100), 1),
            "typical_month": round(typical, 4),
            "hours": int(diff.size), "ceiling": round(ceiling, 4),
            "cleared": round(cleared_f, 4), "margin": round(margin, 3),
            "n_auctions": int(n_auc), "mw_max_auction": float(mw or 0),
            "trim": round(trim, 2), "warnings": "; ".join(why) or None,
            "beat_rate": v.beat_rate, "tail": [round(x, 3) for x in tail],
            "fade": "; ".join(r for r in v.reasons if not r.startswith("spike")) or None,
        })
        if (i + 1) % 10000 == 0:
            print(f"  {i+1:,}/{len(universe):,}  kept {len(results):,}", flush=True)

    results.sort(key=lambda r: -r["margin"])
    print(f"\nvalued universe in {time.time()-t0:,.0f}s", flush=True)
    print(f"kept (margin>1.25x, >={MIN_HOURS}h, >=10c): {len(results):,}")
    print(f"skipped — endpoint not in price data: {skipped_pts:,}; thin history: {skipped_hours:,}")
    faded.sort(key=lambda r: -r["margin"])
    collapse = sum(1 for r in faded if "collapse" in (r["fade"] or ""))
    print(f"removed by the fade detector: {len(faded):,} ({collapse:,} on the two-month collapse trigger)")

    tag = args.target.replace("-", "")
    (REF / f"market_scan_full_{tag}.json").write_text(json.dumps(results))
    (REF / f"market_scan_faded_{tag}.json").write_text(json.dumps(faded[:CAP]))
    # the lost-September lesson: every scan output keeps a dated copy
    dated_copy(REF / f"market_scan_full_{tag}.json")
    dated_copy(REF / f"market_scan_faded_{tag}.json")
    top = results[:CAP]
    if args.dry_run:
        print(f"dry run: {len(top)} rows NOT written to path_valuations")
        return 0

    # ---- 4. publish the shortlist
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        with c.cursor() as cur:
            cur.execute("delete from path_valuations where book = 'Market'")
            cur.executemany("""
                insert into path_valuations
                  (book, source, sink, time_of_use, hedge_type, mw, bids,
                   bid_price, value_mean, value_median, value_p05, value_p95,
                   pct_hours_pos, hours, edge, drivers, warnings,
                   window_start, window_end, ceiling, cleared_price, trim_pct,
                   value_typical)
                values ('Market',%s,%s,%s,%s,%s,%s,null,%s,%s,%s,%s,%s,%s,%s,null,%s,
                        %s,%s,%s,%s,%s,%s)
            """, [(r["source"], r["sink"], r["tou"], r["hedge"],
                   r["mw_max_auction"], r["n_auctions"], r["worth"], r["median"],
                   r["p05"], r["p95"], r["pct_pos"], r["hours"],
                   r["margin"], r["warnings"], W["window_start"], W["window_end"],
                   r["ceiling"], r["cleared"], r["trim"], r["typical_month"])
                  for r in top])
        c.commit()
    print(f"published top {len(top)} to path_valuations as book='Market'")
    print("\nTOP 15 BY VERIFIED MARGIN")
    print(f"{'path':<36}{'TOU':<10}{'ceiling':>8}{'clears':>8}{'margin':>8}{'hrs':>7}{'aucs':>6}")
    for r in top[:15]:
        print(f"{r['source'][:16]+'->'+r['sink'][:16]:<36}{r['tou']:<10}"
              f"{r['ceiling']:>8.2f}{r['cleared']:>8.2f}{r['margin']:>7.1f}x"
              f"{r['hours']:>7,}{r['n_auctions']:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
