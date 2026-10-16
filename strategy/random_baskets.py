#!/usr/bin/env python3
"""Where does each sealed physics book rank among many random baskets?

    python strategy/random_baskets.py [--n 1000] [--books phys_base__m150cap3,...]

For every sealed month and book: draw N random baskets from the same candidate
universe the builder used (paths in the two prior auctions, latest clearing >=
$0.25, no DC ties / Laredo VFT, and <= $3 when the book carries the cap), with
the same number of positions, the same per-source / per-sink limit of 2, the
same MW, and limits set the way the book set them relative to expected
clearing (the book's own median limit / expected-clearing ratio). Each basket
is scored exactly as the sealed books are. Reports the book's profit, the
median and 5th-95th percentile random profit, the book's percentile, and the
same for return on cost. One seeded random basket per month (random__control)
is one draw from this distribution; this replaces it as the comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MIN_CLEAR, MON, NODE_CAP, excluded, month_days

load_dotenv(ROOT / ".env")
DEFAULT_BOOKS = "phys_base__m150,phys_base__m125cap3,phys_base__m150cap3,phys_windy__m150cap3,phys_recent__m150cap3,anch25_base__m150cap3,hist100__m150cap3,market__m125cap3,market_veto__m125cap3,vetorand__control"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--books", default=DEFAULT_BOOKS)
    ap.add_argument("--months", default="")
    args = ap.parse_args()
    want = args.books.split(",")
    out = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        for d in sorted((ARCHIVE / "out" / "sealed").glob("paper_20*_PeakWD")):
            man = json.loads((d / "manifest.json").read_text())
            ym = man["delivery"]
            if not (d / "score.json").exists() or (
                args.months and ym not in args.months.split(",")
            ):
                continue  # unscored months (FEB holdout, OCT/NOV 2026) are never touched
            if ym == "2026-03":
                continue  # built before the 25c floor / tie exclusion / node cap: a different universe
            y, m = map(int, ym.split("-"))
            days = month_days(y, m)
            prior = man["prior_auctions"]
            pclr = {
                sp: float(v)
                for sp, v in c.execute(
                    "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use='PeakWD'",
                    (prior[-1],),
                )
            }
            clr = {
                sp: float(v)
                for sp, v in c.execute(
                    "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use='PeakWD'",
                    (f"{MON[m - 1]}{y}Monthly",),
                )
            }
            cands = c.execute(
                "select distinct source, sink from crr_awards where auction_name = any(%s) and hedge_type='OBL' "
                "and bid_type='BUY' and time_of_use='PeakWD'",
                (prior,),
            ).fetchall()
            univ = [
                (a, b, pclr[a] - pclr[b])
                for a, b in cands
                if a in pclr
                and b in pclr
                and a in clr
                and b in clr
                and not excluded(a)
                and not excluded(b)
                and pclr[a] - pclr[b] >= MIN_CLEAR
            ]
            nodes = sorted({x for a, b, _ in univ for x in (a, b)})
            pr = defaultdict(dict)
            for i in range(0, len(nodes), 100):
                for sp, dd, he, p in c.execute(
                    "select settlement_point, delivery_date, hour_ending, price from dam_spp "
                    "where settlement_point = any(%s) and delivery_date between %s and %s",
                    (nodes[i : i + 100], days[0], days[-1]),
                ):
                    if tou_of(dd, he) == "PeakWD":
                        pr[sp][(dd, he)] = float(p)
            nh = len({h for v in pr.values() for h in v})

            def pay(a, b):
                v = [pr[b][h] - pr[a][h] for h in pr[a] if h in pr[b]]
                return statistics.mean(v) if len(v) >= 0.9 * nh else None

            P = {(a, b): pay(a, b) for a, b, _ in univ}
            univ = [u for u in univ if P[(u[0], u[1])] is not None]
            res = {}
            for book in want:
                f = d / f"{book}.csv"
                if not f.exists():
                    continue
                rows = list(csv.DictReader(open(f)))
                if not rows:
                    continue
                mw = float(rows[0]["mw"])
                k = len(rows)
                lr = statistics.median(float(r["limit"]) / float(r["exp_clear"]) for r in rows)
                cap = 3.0 if "cap3" in book else None
                pool = [u for u in univ if cap is None or u[2] <= cap]

                def score(sel):
                    cost = gain = 0.0
                    for a, b, _ec, lim in sel:
                        if a not in clr or b not in clr:
                            continue  # node absent from the delivery auction: unscored, as in the scorer
                        ac = clr[a] - clr[b]
                        p = P.get((a, b))
                        if p is None or lim < ac:
                            continue
                        cost += mw * nh * ac
                        gain += mw * nh * p
                    return gain - cost, (gain - cost) / cost if cost > 0 else None

                actual = score(
                    [
                        (r["source"], r["sink"], float(r["exp_clear"]), float(r["limit"]))
                        for r in rows
                    ]
                )
                rng = random.Random(f"{ym}|{book}")
                sims = []
                for _ in range(args.n):
                    order = rng.sample(pool, len(pool))
                    sel, ns, nk = [], defaultdict(int), defaultdict(int)
                    for a, b, ec in order:
                        if ns[a] < NODE_CAP and nk[b] < NODE_CAP:
                            sel.append((a, b, ec, ec * lr))
                            ns[a] += 1
                            nk[b] += 1
                            if len(sel) == k:
                                break
                    sims.append(score(sel))
                pf = np.array([s[0] for s in sims])
                rr = np.array([s[1] for s in sims if s[1] is not None])
                res[book] = dict(
                    positions=k,
                    limit_ratio=round(lr, 3),
                    profit=round(actual[0]),
                    rand_p5=round(float(np.percentile(pf, 5))),
                    rand_median=round(float(np.median(pf))),
                    rand_p95=round(float(np.percentile(pf, 95))),
                    pct_profit=round(float((pf < actual[0]).mean() * 100), 1),
                    ret=None if actual[1] is None else round(actual[1], 3),
                    pct_return=None
                    if actual[1] is None or not len(rr)
                    else round(float((rr < actual[1]).mean() * 100), 1),
                )
                r_ = res[book]
                print(
                    f"{ym} {book:26s} k={k:3d} profit {r_['profit']:>10,} | random median {r_['rand_median']:>10,} "
                    f"[5-95%: {r_['rand_p5']:>10,} .. {r_['rand_p95']:>10,}] | percentile {r_['pct_profit']:5.1f} "
                    f"(return pct {r_['pct_return']})",
                    flush=True,
                )
            out[ym] = res
            (d / "random_baskets.json").write_text(json.dumps(dict(n=args.n, books=res), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
