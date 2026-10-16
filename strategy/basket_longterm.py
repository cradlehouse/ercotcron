#!/usr/bin/env python3
"""Diversified cheap-path basket on the 2024-25 long-term auctions (plan
addendum, 16 Oct 2026).

    python strategy/basket_longterm.py [--n 1000]

For each delivery month AUG 2024 - AUG 2025: candidates = PeakWD OBL BUY
single-month paths awarded for that month in long-term sequences 3 and 2, no
DC ties; reference ec = the Seq2 clearing; 0.25 <= ec <= 3. Each of N seeded
baskets takes 60 random candidates (at most 2 per source / sink), bids 5 MW at
1.5 x ec, clears if the Seq1 clearing <= limit, and earns (average DAM spread -
Seq1 clearing) x 5 MW x hours.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import random
import statistics
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MON, NODE_CAP, excluded, month_days

load_dotenv(ROOT / ".env")
TOU, MW, K = "PeakWD", 5, 60
MONTHS = [(2024, m) for m in range(8, 13)] + [(2025, m) for m in range(1, 9)]


RAW = os.path.expanduser("~/ercotcron-archive/ref/crr_longterm_raw")
_NP: dict = {}


def node_prices(auction, period):
    """node -> PeakWD shadow price for one calendar period, read from the original
    ERCOT file (the database table keeps only one period per node)."""
    if auction not in _NP:
        rows = defaultdict(dict)
        f = next((x for x in os.listdir(RAW) if f".{auction}CRRAuctionResults.zip" in x), None)
        if f:
            zf = zipfile.ZipFile(os.path.join(RAW, f))
            name = next(n for n in zf.namelist() if "SourceAndSinkShadowPrices" in n)
            for r in csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="latin-1")):
                if r.get("TimeOfUse") == TOU and r.get("SourceSink"):
                    try:
                        rows[r["CalendarPeriod"]][r["SourceSink"]] = float(r["ShadowPricePerMWH"])
                    except (KeyError, ValueError):
                        pass
        _NP[auction] = rows
    return _NP[auction].get(period, {})


def seq(y, m, k):
    return f"{y}{'1st' if m <= 6 else '2nd'}6AnnualAuctionSeq{k}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    out = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        for y, m in MONTHS:
            ym = f"{y}-{m:02d}"
            period = f"{MON[m - 1]}_{y}"
            days = month_days(y, m)

            s1, s2 = node_prices(seq(y, m, 1), period), node_prices(seq(y, m, 2), period)
            if not s1 or not s2:
                print(f"{ym}: missing Seq1 or Seq2 prices - skipped", flush=True)
                continue
            cands = c.execute(
                "select distinct source, sink from crr_awards where auction_name = any(%s) and hedge_type='OBL' "
                "and bid_type='BUY' and time_of_use=%s and start_date=%s and end_date=%s",
                ([seq(y, m, 2), seq(y, m, 3)], TOU, days[0], days[-1]),
            ).fetchall()
            pool = [
                (a, b, s2[a] - s2[b])
                for a, b in cands
                if a in s2
                and b in s2
                and a in s1
                and b in s1
                and not excluded(a)
                and not excluded(b)
                and 0.25 <= s2[a] - s2[b] <= 3.0
            ]
            nodes = sorted({x for a, b, _ in pool for x in (a, b)})
            pr = defaultdict(dict)
            for i in range(0, len(nodes), 100):
                for sp, d, he, p in c.execute(
                    "select settlement_point, delivery_date, hour_ending, price from dam_spp "
                    "where settlement_point = any(%s) and delivery_date between %s and %s",
                    (nodes[i : i + 100], days[0], days[-1]),
                ):
                    if tou_of(d, he) == TOU:
                        pr[sp][(d, he)] = float(p)
            nh = len({h for v in pr.values() for h in v})
            pay = {}
            for a, b, _ in pool:
                v = [pr[b][h] - pr[a][h] for h in pr.get(a, {}) if h in pr.get(b, {})]
                if len(v) >= 0.9 * nh:
                    pay[(a, b)] = statistics.mean(v)
            pool = [p for p in pool if (p[0], p[1]) in pay]
            if len(pool) < K:
                print(f"{ym}: only {len(pool)} candidates - skipped", flush=True)
                continue
            rng = random.Random(f"{ym}|ltbasket")
            sims, clears = [], []
            for _ in range(args.n):
                order = rng.sample(pool, len(pool))
                sel, ns, nk = [], defaultdict(int), defaultdict(int)
                for a, b, ec in order:
                    if ns[a] < NODE_CAP and nk[b] < NODE_CAP:
                        sel.append((a, b, ec))
                        ns[a] += 1
                        nk[b] += 1
                        if len(sel) == K:
                            break
                prof, cl = 0.0, 0
                for a, b, ec in sel:
                    p1 = s1[a] - s1[b]
                    if p1 <= 1.5 * ec:
                        prof += MW * nh * (pay[(a, b)] - p1)
                        cl += 1
                sims.append(prof)
                clears.append(cl)
            sims = np.array(sims)
            allp = [(pay[(a, b)], s1[a] - s1[b]) for a, b, _ in pool]
            out[ym] = dict(
                candidates=len(pool),
                hours=nh,
                median=round(float(np.median(sims))),
                p5=round(float(np.percentile(sims, 5))),
                p95=round(float(np.percentile(sims, 95))),
                share_profitable=round(float((sims > 0).mean()), 3),
                cleared_median=int(np.median(clears)),
                pool_paid_over_price=round(sum(p for p, _ in allp) / sum(q for _, q in allp), 3)
                if sum(q for _, q in allp) > 0
                else None,
            )
            r = out[ym]
            print(
                f"{ym}: {r['candidates']:4d} candidates; median basket {r['median']:>10,} "
                f"[5%: {r['p5']:>10,}  95%: {r['p95']:>10,}]; {r['share_profitable']:.0%} of baskets profitable; "
                f"pool paid {r['pool_paid_over_price']}x its Seq1 price",
                flush=True,
            )
    meds = [r["median"] for r in out.values()] or [0]
    pos = sum(1 for v in meds if v > 0)
    print(
        f"months tested {len(meds)}; median basket profitable in {pos}; sum of medians {sum(meds):,}; "
        f"worst month median {min(meds):,}; PASS={pos >= 9 and sum(meds) > 0} (untested months count as failures: {13 - len(meds)})"
    )
    outd = ARCHIVE / "out" / "experiment"
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "basket_longterm.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
