#!/usr/bin/env python3
"""Sell-side test (plan addendum, 16 Oct 2026): sell expensive popular paths.

    python strategy/sell_side.py [--n 1000]

Selling A->B is buying B->A at a negative price. For each development month:
universe = the two prior auctions' PeakWD OBL BUY paths, no DC ties, last
clearing P_last >= threshold. An offer clears when the actual clearing
P_act >= 0.8 x P_last; a cleared sale earns 5 MW x hours x (P_act - payout),
payout = the average DAM spread (sink - source) of A->B over the month.
Books S3, S5 (the 60 most expensive above $3 / $5) and S3h (above $3, ranked by
P_last minus the path's average spread over the 100 days to asof), at most 2 per
source and per sink, each ranked against N random baskets from its own pool.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MON, NODE_CAP, excluded, month_days

load_dotenv(ROOT / ".env")
DEV = ("2025-11", "2025-12", "2026-01", "2026-03", "2026-05", "2026-07")
TOU, MW, KEEP, K = "PeakWD", 5, 0.8, 60


def prices(c, nodes, d0, d1):
    pr = defaultdict(dict)
    for i in range(0, len(nodes), 100):
        for sp, d, he, p in c.execute(
            "select settlement_point, delivery_date, hour_ending, price from dam_spp "
            "where settlement_point = any(%s) and delivery_date between %s and %s",
            (nodes[i : i + 100], d0, d1),
        ):
            if tou_of(d, he) == TOU:
                pr[sp][(d, he)] = float(p)
    return pr


def spread(pr, a, b, need=None):
    v = [pr[b][h] - pr[a][h] for h in pr.get(a, {}) if h in pr.get(b, {})]
    if not v or (need and len(v) < need):
        return None
    return statistics.mean(v)


def pick(pool, key, rng=None):
    order = rng.sample(pool, len(pool)) if rng else sorted(pool, key=key)
    sel, ns, nk = [], defaultdict(int), defaultdict(int)
    for p in order:
        a, b = p[0], p[1]
        if ns[a] < NODE_CAP and nk[b] < NODE_CAP:
            sel.append(p)
            ns[a] += 1
            nk[b] += 1
            if len(sel) == K:
                break
    return sel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    out = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        for ym in DEV:
            man = json.loads(
                (ARCHIVE / "out" / "sealed" / f"paper_{ym}_{TOU}" / "manifest.json").read_text()
            )
            asof = date.fromisoformat(man["asof"])
            y, m = map(int, ym.split("-"))
            days = month_days(y, m)
            prior = man["prior_auctions"]

            def clearing(auction):
                return {
                    sp: float(v)
                    for sp, v in c.execute(
                        "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use=%s",
                        (auction, TOU),
                    )
                }

            pclr, clr = clearing(prior[-1]), clearing(f"{MON[m - 1]}{y}Monthly")
            cands = c.execute(
                "select distinct source, sink from crr_awards where auction_name = any(%s) and hedge_type='OBL' "
                "and bid_type='BUY' and time_of_use=%s",
                (prior, TOU),
            ).fetchall()
            base = [
                (a, b, pclr[a] - pclr[b])
                for a, b in cands
                if a in pclr
                and b in pclr
                and a in clr
                and b in clr
                and not excluded(a)
                and not excluded(b)
                and pclr[a] - pclr[b] >= 3.0
            ]
            nodes = sorted({x for a, b, _ in base for x in (a, b)})
            pr = prices(c, nodes, days[0], days[-1])
            nh = len({h for v in pr.values() for h in v})
            hist = prices(c, nodes, asof - timedelta(days=100), asof - timedelta(days=1))
            univ = []
            for a, b, pl in base:
                pay = spread(pr, a, b, 0.9 * nh)
                if pay is None:
                    continue
                h = spread(hist, a, b)
                univ.append((a, b, pl, clr[a] - clr[b], pay, h))

            def score(sel):
                prof, worst, cleared = 0.0, 0.0, 0
                for _a, _b, pl, pact, pay, _h in sel:
                    if pact >= KEEP * pl:
                        p = MW * nh * (pact - pay)
                        prof += p
                        worst = min(worst, p)
                        cleared += 1
                return prof, worst, cleared

            res = {}
            books = {
                "S3": ([u for u in univ if u[2] >= 3.0], lambda u: (-u[2], u[0], u[1])),
                "S5": ([u for u in univ if u[2] >= 5.0], lambda u: (-u[2], u[0], u[1])),
                "S3h": (
                    [u for u in univ if u[2] >= 3.0 and u[5] is not None],
                    lambda u: (-(u[2] - u[5]), u[0], u[1]),
                ),
            }
            for name, (pool, key) in books.items():
                sel = pick(pool, key)
                prof, worst, cl = score(sel)
                rng = random.Random(f"{ym}|sell|{name}")
                sims = np.array([score(pick(pool, None, rng))[0] for _ in range(args.n)])
                res[name] = dict(
                    pool=len(pool),
                    positions=len(sel),
                    cleared=cl,
                    profit=round(prof),
                    worst_path=round(worst),
                    random_median=round(float(np.median(sims))),
                    random_p5=round(float(np.percentile(sims, 5))),
                    random_p95=round(float(np.percentile(sims, 95))),
                    percentile=round(float((sims < prof).mean() * 100), 1),
                    pool_paid_over_price=round(sum(u[4] for u in pool) / sum(u[3] for u in pool), 3)
                    if pool and sum(u[3] for u in pool) > 0
                    else None,
                )
                r = res[name]
                print(
                    f"{ym} {name:4s} pool {r['pool']:4d} sold {r['cleared']:2d}/{r['positions']:2d} profit {r['profit']:>10,} "
                    f"worst path {r['worst_path']:>9,} | random median {r['random_median']:>10,} "
                    f"[{r['random_p5']:>10,} .. {r['random_p95']:>10,}] pct {r['percentile']:5.1f} | "
                    f"pool paid/price {r['pool_paid_over_price']}",
                    flush=True,
                )
            out[ym] = res
    outd = ARCHIVE / "out" / "experiment"
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "sell_side.json").write_text(json.dumps(out, indent=1))
    for name in ("S3", "S5", "S3h"):
        ps = [out[m][name]["profit"] for m in out]
        print(
            f"{name}: total {sum(ps):,}; months positive {sum(p > 0 for p in ps)}/{len(ps)}; "
            f"median percentile {statistics.median(out[m][name]['percentile'] for m in out)}; "
            f"worst month {min(ps):,}; worst path {min(out[m][name]['worst_path'] for m in out):,}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
