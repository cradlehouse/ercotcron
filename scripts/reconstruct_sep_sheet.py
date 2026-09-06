#!/usr/bin/env python3
"""Whole-market scan: value every path the CRR auctions have actually cleared.

    python strategy/market_scan.py

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
import json
import os
import pathlib
import time

import numpy as np
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg  # noqa: E402

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"
CACHES = [pathlib.Path.home() / "ercotcron-archive" / "cache", pathlib.Path("/tmp")]
# Window sep25..jun26 (10 months) + the target month's own history (oct24;
# oct25 sits inside the window). Jul/Aug/Sep 2026 deliberately absent: the
# standing rule holds out the trailing 2 months, and monthly caches force
# whole-month cuts, so the window ends Jun 30.
MONTH_TAGS = ["sep24", "sep25", "oct25", "nov25", "dec25", "jan26", "feb26",
              "mar26", "apr26", "may26", "jun26"]
TARGET_MONTHS = ("2024-09", "2025-09")   # SEPTEMBER — this is the reconstruction
MIN_HOURS = 2000
MATERIALITY = 0.10
CAP = 400          # rows written to the platform


def tou_of(d: dt.date, he: int) -> str:
    if not (7 <= he <= 22):
        return "Off-peak"
    return "PeakWD" if d.weekday() < 5 else "PeakWE"


def main() -> int:
    t0 = time.time()

    # ---- 1. price matrix from local caches
    print("loading cached DAM months...", flush=True)
    hour_keys: list[tuple[dt.date, int]] = []
    point_idx: dict[str, int] = {}
    cols: list[dict[int, float]] = []      # per hour: point index -> price
    for tag in MONTH_TAGS:
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
    months = sorted(set(month_arr))

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
                       avg(clearing_price) cp, sum(mw) mw, max(ingested_at) ing
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
        exp = json.loads((REF / "constraint_exposure.json").read_text())
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
    results = []
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
        permonth = [float(pay[mmask == m].mean()) for m in months if (mmask == m).sum() >= 100]
        typical = float(np.median(permonth)) if len(permonth) >= 6 else worth
        # A regime that has already collapsed must not be priced off its fat
        # past: three scan headliners went NEGATIVE in the held-out July while
        # their medians still read $2-7. Price off the smaller of typical and
        # the recent three months, and flag the decay.
        recent = float(np.mean(permonth[-3:])) if len(permonth) >= 3 else typical
        fading = len(permonth) >= 6 and recent < 0.3 * typical
        typical = min(typical, max(recent, 0.0))
        # The product being bid delivers in SEPTEMBER. A year-round blend is
        # nonsense for a seasonal quantity, so cap the value at what actual
        # Septembers paid (2024 and 2025) where that history exists.
        sep_hist = [float(pay[mmask == m].mean()) for m in TARGET_MONTHS if (mmask == m).sum() >= 100]
        if sep_hist:
            typical = min(typical, max(float(np.mean(sep_hist)), 0.0))
        cleared_f = float(cleared or 0)
        trim, why = 0.0, []
        s = stale_nodes.get(src) or stale_nodes.get(snk)
        if s:
            trim += 0.30
            why.append(f"{s}: re-rated <90d")
        if med > 0 and worth > 3 * med:
            trim += 0.25
            why.append("spike-driven")
        if fading:
            why.append("congestion fading — recent months far below the average")
        ceiling = typical * (1 - min(trim, 0.75))
        # Near-zero clearing prices make margin ratios explode into nonsense
        # (a $4 path over a $0.00 clear is "1600x"), and one-auction paths are
        # a single observation. Floors: the auction must have priced it at
        # least a nickel, across >= 3 auctions, and the absolute gap must be
        # worth collecting, not just the ratio.
        if fading or ceiling < MATERIALITY or cleared_f < 0.05 or int(n_auc) < 3:
            continue
        margin = ceiling / cleared_f
        if margin <= 1.25 or (ceiling - cleared_f) < 0.10:
            continue
        results.append({
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
        })
        if (i + 1) % 10000 == 0:
            print(f"  {i+1:,}/{len(universe):,}  kept {len(results):,}", flush=True)

    results.sort(key=lambda r: -r["margin"])
    print(f"\nvalued universe in {time.time()-t0:,.0f}s", flush=True)
    print(f"kept (margin>1.25x, >={MIN_HOURS}h, >=10c): {len(results):,}")
    print(f"skipped — endpoint not in price data: {skipped_pts:,}; thin history: {skipped_hours:,}")

    (REF / "market_scan_full.json").write_text(json.dumps(results))
    top = results[:CAP]

    # ---- 4. freeze into sheet_snapshots as the reconstructed SEP vintage
    HOURS = {"PeakWD": 336, "PeakWE": 144, "Off-peak": 240}
    def derive(r):
        margin_limit = r["ceiling"] / 1.5
        clr = r["cleared"]
        ref = min(margin_limit, max(3 * clr, 0.1)) if clr and clr < 0.5 else margin_limit
        if r["worth"] is None or ref < 0.1:
            tier = "red"
        elif clr and clr > 0 and ref / clr <= 1.0:
            tier = "red"
        else:
            tier = "amber"   # Market rows are never green
        if tier == "red":
            mw = 0
        else:
            rate = clr or ref or 0.1
            by_budget = int(250 / max(HOURS.get(r["tou"], 300) * rate, 1))
            by_liq = max(int((r["mw_max_auction"] or 10) / 2), 1)
            mw = max(1, min(by_budget if by_budget > 0 else 1, by_liq, 200))
        return ref, tier, mw

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        with c.cursor() as cur:
            cur.execute("select count(*) from sheet_snapshots where sheet = 'SEP2026Monthly-reconstructed'")
            if cur.fetchone()[0] > 0:
                print("reconstruction already frozen; not duplicating")
                return 0
            n = 0
            for r in results[:CAP]:
                ref, tier, mw = derive(r)
                cur.execute("""insert into sheet_snapshots
                    (sheet, source, sink, time_of_use, hedge_type, book, tier,
                     ref_limit, suggested_mw, typical, worth, cleared_basis)
                    values ('SEP2026Monthly-reconstructed', %s,%s,%s,%s,'Market',%s,%s,%s,%s,%s,%s)""",
                    (r["source"], r["sink"], r["tou"], r["hedge"], tier,
                     round(ref, 4), mw, r["typical_month"], r["worth"], r["cleared"]))
                n += 1
        c.commit()
    print(f"froze {n} reconstructed SEP rows (inputs pinned to 2026-08-11; trims approximate)")
    
    print("\nTOP 15 BY VERIFIED MARGIN")
    print(f"{'path':<36}{'TOU':<10}{'ceiling':>8}{'clears':>8}{'margin':>8}{'hrs':>7}{'aucs':>6}")
    for r in top[:15]:
        print(f"{r['source'][:16]+'->'+r['sink'][:16]:<36}{r['tou']:<10}"
              f"{r['ceiling']:>8.2f}{r['cleared']:>8.2f}{r['margin']:>7.1f}x"
              f"{r['hours']:>7,}{r['n_auctions']:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
