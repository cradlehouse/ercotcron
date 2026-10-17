#!/usr/bin/env python3
"""Long-term cheap-path basket: score a strip so far, or freeze a forward book.

    python strategy/lt_basket.py score --strip 2026-2nd    # JUL-DEC 2026, months to date
    python strategy/lt_basket.py freeze --strip 2027-1st --budget 25000
    python strategy/lt_basket.py evaluate --strip 2027-1st   # fills, then payouts month by month

Rule (tested AUG 2024 - AUG 2025): for each month of the strip, candidates are
PeakWD OBL BUY single-month paths awarded in sequences 2 and 3, no DC ties /
LARDVFT*, with the Seq2 clearing (source - sink) between $0.25 and $3; a basket
takes 60 of them at random, at most 2 per source and per sink, and bids 1.5x
the Seq2 price; a bid clears when the final sequence (Seq1) clears at or below
it and earns (average DAM spread - Seq1 price) x MW x hours.

score: 1,000 baskets per month at 5 MW; months still in progress are scored
on the hours so far and flagged. freeze: one seeded basket per month, MW set so
the maximum spend (every bid clearing at its limit) is at most --budget per
month; writes ARCHIVE/out/sealed/lt_<strip>/ with SHA-256s and refuses to
overwrite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MON, NODE_CAP, excluded, month_days

load_dotenv(ROOT / ".env")
TOU, K, LIMIT_X = "PeakWD", 60, 1.5


def seq(y, half, k):
    return f"{y}{half}6AnnualAuctionSeq{k}"


def months_of(y, half):
    return [(y, m) for m in (range(1, 7) if half == "1st" else range(7, 13))]


def node_prices(c, auction, period):
    return {
        sp: float(v)
        for sp, v in c.execute(
            "select settlement_point, shadow_price from crr_point_prices "
            "where auction_name=%s and time_of_use=%s and calendar_period=%s",
            (auction, TOU, period),
        )
    }


def pool_for(c, y, half, m):
    days = month_days(y, m)
    period = f"{MON[m - 1]}_{y}"
    s2 = node_prices(c, seq(y, half, 2), period)
    cands = c.execute(
        "select distinct source, sink from crr_awards where auction_name = any(%s) and hedge_type='OBL' "
        "and bid_type='BUY' and time_of_use=%s and start_date=%s and end_date=%s",
        ([seq(y, half, 2), seq(y, half, 3)], TOU, days[0], days[-1]),
    ).fetchall()
    return s2, [
        (a, b, s2[a] - s2[b])
        for a, b in cands
        if a in s2
        and b in s2
        and not excluded(a)
        and not excluded(b)
        and 0.25 <= s2[a] - s2[b] <= 3.0
    ]


def draw(pool, rng):
    sel, ns, nk = [], defaultdict(int), defaultdict(int)
    for a, b, ec in rng.sample(pool, len(pool)):
        if ns[a] < NODE_CAP and nk[b] < NODE_CAP:
            sel.append((a, b, ec))
            ns[a] += 1
            nk[b] += 1
            if len(sel) == K:
                break
    return sel


def peak_hours(y, m):
    return sum(1 for d in month_days(y, m) for he in range(1, 25) if tou_of(d, he) == TOU)


def score(c, y, half, n):
    out = {}
    today = date.today()
    for yy, m in months_of(y, half):
        ym = f"{yy}-{m:02d}"
        days = month_days(yy, m)
        if days[0] >= today:
            out[ym] = {"status": "not started"}
            print(f"{ym}: not started", flush=True)
            continue
        s1 = node_prices(c, seq(y, half, 1), f"{MON[m - 1]}_{yy}")
        _s2, pool = pool_for(c, y, half, m)
        pool = [p for p in pool if p[0] in s1 and p[1] in s1]
        nodes = sorted({x for a, b, _ in pool for x in (a, b)})
        pr = defaultdict(dict)
        for i in range(0, len(nodes), 100):
            for sp, d, he, p in c.execute(
                "select settlement_point, delivery_date, hour_ending, price from dam_spp "
                "where settlement_point = any(%s) and delivery_date between %s and %s",
                (nodes[i : i + 100], days[0], min(days[-1], today)),
            ):
                if tou_of(d, he) == TOU:
                    pr[sp][(d, he)] = float(p)
        nh = len({h for v in pr.values() for h in v})
        full = peak_hours(yy, m)
        pay = {}
        for a, b, _ in pool:
            v = [pr[b][h] - pr[a][h] for h in pr.get(a, {}) if h in pr.get(b, {})]
            if len(v) >= 0.9 * nh and v:
                pay[(a, b)] = statistics.mean(v)
        pool = [p for p in pool if (p[0], p[1]) in pay]
        if len(pool) < K:
            out[ym] = {"status": f"only {len(pool)} candidates"}
            print(f"{ym}: only {len(pool)} candidates - not testable", flush=True)
            continue
        rng = random.Random(f"{ym}|ltbasket")
        profs, costs = [], []
        for _ in range(n):
            prof = cost = 0.0
            for a, b, ec in draw(pool, rng):
                p1 = s1[a] - s1[b]
                if p1 <= LIMIT_X * ec:
                    prof += 5 * nh * (pay[(a, b)] - p1)
                    cost += 5 * nh * p1
            profs.append(prof)
            costs.append(cost)
        pa, ca = np.array(profs), np.array(costs)
        status = "complete" if nh >= 0.95 * full else f"in progress ({nh} of {full} peak hours)"
        out[ym] = dict(
            status=status,
            candidates=len(pool),
            median_profit=round(float(np.median(pa))),
            p5=round(float(np.percentile(pa, 5))),
            p95=round(float(np.percentile(pa, 95))),
            median_cost=round(float(np.median(ca))),
            share_profitable=round(float((pa > 0).mean()), 3),
        )
        r = out[ym]
        print(
            f"{ym} [{status}]: {r['candidates']} candidates; median basket cost ${r['median_cost']:,} -> "
            f"profit ${r['median_profit']:,} [5%: {r['p5']:,}  95%: {r['p95']:,}]; "
            f"{r['share_profitable']:.0%} of baskets profitable",
            flush=True,
        )
    return out


def freeze(c, y, half, budget):
    d = ARCHIVE / "out" / "sealed" / f"lt_{y}-{half}"
    if d.exists():
        raise SystemExit(f"{d} exists - a frozen book is never rebuilt")
    have = {a for (a,) in c.execute("select auction_name from crr_auctions")}
    if seq(y, half, 1) in have:
        raise SystemExit(
            "the final sequence's results are already loaded - this would not be a forward test"
        )
    books, summary = {}, {}
    for yy, m in months_of(y, half):
        ym = f"{yy}-{m:02d}"
        _s2, pool = pool_for(c, y, half, m)
        if len(pool) < K:
            summary[ym] = {"status": f"only {len(pool)} candidates - no book"}
            continue
        sel = draw(pool, random.Random(f"{ym}|ltforward"))
        hrs = peak_hours(yy, m)
        max_per_mw = sum(LIMIT_X * ec for _a, _b, ec in sel) * hrs
        mw = math.floor(budget / max_per_mw * 10) / 10
        books[ym] = [
            dict(
                source=a,
                sink=b,
                tou=TOU,
                mw=mw,
                limit=round(LIMIT_X * ec, 4),
                seq2_price=round(ec, 4),
            )
            for a, b, ec in sel
        ]
        summary[ym] = dict(
            paths=len(sel),
            mw_per_path=mw,
            peak_hours=hrs,
            max_spend=round(max_per_mw * mw),
            spend_at_seq2_prices=round(sum(ec for *_, ec in sel) * hrs * mw),
        )
    d.mkdir(parents=True)
    shas = {}
    for ym, rows in books.items():
        p = d / f"{ym}.csv"
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        shas[ym] = hashlib.sha256(p.read_bytes()).hexdigest()
    man = dict(
        strip=f"{y} {half} 6 months",
        built=str(date.today()),
        final_sequence=seq(y, half, 1),
        rule="60 random PeakWD OBL paths per month from Seq2/Seq3 awards, Seq2 price $0.25-3, 2 per node, "
        "limit 1.5 x Seq2 price, MW sized to max spend <= budget",
        budget_per_month=budget,
        months=summary,
        sha256=shas,
    )
    (d / "manifest.json").write_text(json.dumps(man, indent=1))
    print(json.dumps(summary, indent=1))
    print(f"sealed {len(books)} monthly books -> {d}")
    return man


def evaluate(c, y, half):
    """Score a sealed forward book: which bids cleared in the final sequence, at
    what cost, and what each month has paid so far. Writes evaluation.json next
    to the sealed books (the books themselves are never touched)."""
    d = ARCHIVE / "out" / "sealed" / f"lt_{y}-{half}"
    man = json.loads((d / "manifest.json").read_text())
    for ym, sha in man["sha256"].items():
        if hashlib.sha256((d / f"{ym}.csv").read_bytes()).hexdigest() != sha:
            raise SystemExit(f"{ym}.csv does not match its sealed SHA-256")
    have = {a for (a,) in c.execute("select auction_name from crr_auctions")}
    if man["final_sequence"] not in have:
        print(
            f"{man['final_sequence']} results are not posted yet - nothing to evaluate", flush=True
        )
        return None
    today = date.today()
    res, tot_cost, tot_profit = {}, 0.0, 0.0
    for ym in sorted(man["sha256"]):
        yy, m = map(int, ym.split("-"))
        days = month_days(yy, m)
        rows = list(csv.DictReader(open(d / f"{ym}.csv")))
        s1 = node_prices(c, man["final_sequence"], f"{MON[m - 1]}_{yy}")
        won = [
            (r, s1[r["source"]] - s1[r["sink"]])
            for r in rows
            if r["source"] in s1
            and r["sink"] in s1
            and s1[r["source"]] - s1[r["sink"]] <= float(r["limit"])
        ]
        hrs = peak_hours(yy, m)
        cost = sum(p1 * float(r["mw"]) * hrs for r, p1 in won)
        out = dict(bids=len(rows), cleared=len(won), cost=round(cost))
        if days[0] < today and won:
            nodes = sorted({x for r, _ in won for x in (r["source"], r["sink"])})
            pr = defaultdict(dict)
            for i in range(0, len(nodes), 100):
                for sp, dd, he, p in c.execute(
                    "select settlement_point, delivery_date, hour_ending, price from dam_spp "
                    "where settlement_point = any(%s) and delivery_date between %s and %s",
                    (nodes[i : i + 100], days[0], min(days[-1], today)),
                ):
                    if tou_of(dd, he) == TOU:
                        pr[sp][(dd, he)] = float(p)
            nh = len({h for v in pr.values() for h in v})
            paid = 0.0
            for r, _p1 in won:
                a, b = r["source"], r["sink"]
                v = [pr[b][h] - pr[a][h] for h in pr.get(a, {}) if h in pr.get(b, {})]
                if v:
                    paid += statistics.mean(v) * float(r["mw"]) * nh
            cost_so_far = cost * nh / hrs
            out.update(
                peak_hours_so_far=nh,
                of_hours=hrs,
                payout_so_far=round(paid),
                profit_so_far=round(paid - cost_so_far),
                status="complete" if nh >= 0.95 * hrs else "in progress",
            )
            tot_cost += cost_so_far
            tot_profit += paid - cost_so_far
        else:
            out["status"] = "not started"
        res[ym] = out
        print(f"{ym}: {json.dumps(out)}", flush=True)
    summary = dict(
        evaluated=str(today),
        months=res,
        cost_so_far=round(tot_cost),
        profit_so_far=round(tot_profit),
    )
    (d / "evaluation.json").write_text(json.dumps(summary, indent=1))
    print(f"so far: cost ${tot_cost:,.0f}, profit ${tot_profit:,.0f}")
    return summary


def paper(c, y, half, budget):
    """Build the strip's book exactly as freeze() would have (one seeded basket a
    month, MW sized to the budget), then score it: fills at the final sequence,
    cost, and DAM payout (months in progress on the hours so far)."""
    today = date.today()
    res, tot = {}, dict(cost=0.0, payout=0.0)
    for yy, m in months_of(y, half):
        ym = f"{yy}-{m:02d}"
        days = month_days(yy, m)
        if days[0] < date(2024, 7, 27) or days[0] >= today:
            res[ym] = {"status": "no DAM prices" if days[0] < date(2024, 7, 27) else "not started"}
            continue
        s1 = node_prices(c, seq(y, half, 1), f"{MON[m - 1]}_{yy}")
        _s2, pool = pool_for(c, y, half, m)
        pool = [p for p in pool if p[0] in s1 and p[1] in s1]
        if len(pool) < K:
            res[ym] = {"status": f"only {len(pool)} candidates - no book"}
            continue
        sel = draw(pool, random.Random(f"{ym}|ltforward"))
        hrs = peak_hours(yy, m)
        mw = math.floor(budget / (sum(LIMIT_X * ec for _a, _b, ec in sel) * hrs) * 10) / 10
        won = [(a, b, s1[a] - s1[b]) for a, b, ec in sel if s1[a] - s1[b] <= LIMIT_X * ec]
        nodes = sorted({x for a, b, _ in won for x in (a, b)})
        pr = defaultdict(dict)
        for i in range(0, len(nodes), 100):
            for sp, dd, he, p in c.execute(
                "select settlement_point, delivery_date, hour_ending, price from dam_spp "
                "where settlement_point = any(%s) and delivery_date between %s and %s",
                (nodes[i : i + 100], days[0], min(days[-1], today)),
            ):
                if tou_of(dd, he) == TOU:
                    pr[sp][(dd, he)] = float(p)
        nh = len({h for v in pr.values() for h in v})
        cost = sum(p1 for _a, _b, p1 in won) * mw * nh
        paid = 0.0
        for a, b, _p1 in won:
            v = [pr[b][h] - pr[a][h] for h in pr.get(a, {}) if h in pr.get(b, {})]
            if v:
                paid += statistics.mean(v) * mw * nh
        status = "complete" if nh >= 0.95 * hrs else f"in progress ({nh} of {hrs} peak hours)"
        res[ym] = dict(
            status=status,
            bids=len(sel),
            cleared=len(won),
            mw=mw,
            cost=round(cost),
            payout=round(paid),
            profit=round(paid - cost),
        )
        tot["cost"] += cost
        tot["payout"] += paid
        r = res[ym]
        print(
            f"{ym} [{status}]: {r['cleared']}/{r['bids']} bids cleared at {mw} MW; cost ${r['cost']:,}; "
            f"paid ${r['payout']:,}; profit ${r['profit']:,}",
            flush=True,
        )
    print(
        f"strip {y} {half}: cost ${tot['cost']:,.0f}; paid ${tot['payout']:,.0f}; "
        f"profit ${tot['payout'] - tot['cost']:,.0f}",
        flush=True,
    )
    return dict(
        months=res,
        cost=round(tot["cost"]),
        payout=round(tot["payout"]),
        profit=round(tot["payout"] - tot["cost"]),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("score", "freeze", "evaluate", "paper"))
    ap.add_argument("--strip", required=True, help="e.g. 2026-2nd or 2027-1st")
    ap.add_argument("--budget", type=float, default=25000)
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    y, half = args.strip.split("-")
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        if args.mode == "score":
            res = score(c, int(y), half, args.n)
            (ARCHIVE / "out" / "experiment").mkdir(parents=True, exist_ok=True)
            (ARCHIVE / "out" / "experiment" / f"lt_basket_{args.strip}.json").write_text(
                json.dumps(res, indent=1)
            )
        elif args.mode == "paper":
            res = paper(c, int(y), half, args.budget)
            (ARCHIVE / "out" / "experiment").mkdir(parents=True, exist_ok=True)
            (ARCHIVE / "out" / "experiment" / f"lt_paper_{args.strip}.json").write_text(
                json.dumps(res, indent=1)
            )
        elif args.mode == "freeze":
            freeze(c, int(y), half, args.budget)
        else:
            evaluate(c, int(y), half)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
