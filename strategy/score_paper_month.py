#!/usr/bin/env python3
"""Score a FROZEN paper month (strategy/paper_month.py --freeze).

    python strategy/score_paper_month.py --delivery 2026-03 [--tou PeakWD]

Refuses anything but a sealed slate whose files still match the manifest's
SHA-256s. For every book:
  cleared   a buy clears when its limit >= the path's actual clearing price
            (source - sink nodal price in the delivery month's auction)
  payout    the path's average DAM spread (sink - source) over the delivery
            month's TOU hours, $/MWh
  profit    MW x hours x (payout - clearing) summed over cleared bids
Books are ranked by profit and compared with random__control; the report is
written next to the sealed books (score.json) and never alters them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MON, month_days

load_dotenv(ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery", required=True)
    ap.add_argument("--tou", default="PeakWD")
    args = ap.parse_args()
    d = ARCHIVE / "out" / "sealed" / f"paper_{args.delivery}_{args.tou}"
    man = json.loads((d / "manifest.json").read_text())
    for k, sha in man["sha256"].items():
        if hashlib.sha256((d / f"{k}.csv").read_bytes()).hexdigest() != sha:
            raise SystemExit(f"{k}.csv does not match its sealed SHA-256")
    books = {k: list(csv.DictReader(open(d / f"{k}.csv"))) for k in man["sha256"]}
    y, m = map(int, args.delivery.split("-"))
    days = month_days(y, m)
    auction = f"{MON[m - 1]}{y}Monthly"
    paths = {(r["source"], r["sink"]) for rws in books.values() for r in rws}
    nodes = sorted({x for p in paths for x in p})
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        clear = dict(
            c.execute(
                "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use=%s",
                (auction, args.tou),
            ).fetchall()
        )
        if not clear:
            raise SystemExit(f"no {auction} {args.tou} clearing prices")
        price = defaultdict(dict)
        for i in range(0, len(nodes), 100):  # batches: one big query can drop the connection
            for sp, dd, he, pr in c.execute(
                """select settlement_point, delivery_date, hour_ending, price from dam_spp
                    where settlement_point = any(%s) and delivery_date between %s and %s""",
                (nodes[i : i + 100], days[0], days[-1]),
            ):
                if tou_of(dd, he) == args.tou:
                    price[sp][(dd, he)] = float(pr)
    hours = sorted({k for v in price.values() for k in v})
    nh = len(hours)

    def payout(src, snk):
        a, b = price.get(src, {}), price.get(snk, {})
        v = [b[h] - a[h] for h in hours if h in a and h in b]
        return statistics.mean(v) if len(v) >= 0.9 * nh else None

    pay = {p: payout(*p) for p in paths}
    rep = {}
    for k, rws in books.items():
        n = cl = wins = 0
        cost = gain = 0.0
        for r in rws:
            src, snk, mw, lim = r["source"], r["sink"], float(r["mw"]), float(r["limit"])
            if src not in clear or snk not in clear or pay[(src, snk)] is None:
                continue
            n += 1
            ac = float(clear[src]) - float(clear[snk])
            if lim >= ac:
                cl += 1
                cost += mw * nh * ac
                gain += mw * nh * pay[(src, snk)]
                wins += pay[(src, snk)] > ac
        rep[k] = dict(
            bids=len(rws),
            scored=n,
            cleared=cl,
            cost=round(cost),
            payout=round(gain),
            profit=round(gain - cost),
            win_rate=round(wins / cl, 3) if cl else None,
            roi=round((gain - cost) / cost, 3) if cost > 0 else None,
        )
    ctrl = rep.get("random__control", {}).get("profit")
    order = sorted(rep, key=lambda k: -rep[k]["profit"])
    print(f"{auction} {args.tou}: {nh} hours scored; control profit ${ctrl:,}")
    print(
        f"{'book':28s} {'bids':>4s} {'clr':>4s} {'cost':>10s} {'payout':>10s} {'profit':>10s} {'return':>7s} {'win':>5s}"
    )
    for k in order:
        r = rep[k]
        wr = f"{r['win_rate']:.0%}" if r["win_rate"] is not None else "-"
        ro = f"{r['roi']:.0%}" if r["roi"] is not None else "-"
        print(
            f"{k:28s} {r['bids']:4d} {r['cleared']:4d} {r['cost']:10,} {r['payout']:10,} {r['profit']:10,} {ro:>7s} {wr:>5s}"
        )
    (d / "score.json").write_text(json.dumps(dict(auction=auction, hours=nh, books=rep), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
