#!/usr/bin/env python3
"""Expanding-window walk-forward on the constraint-conditioned DART pair.

    python strategy/walk_forward_constraints.py

Tim's design, and the right one:

    fit 2024-08..2025-01  -> test 2025-02..2025-03
    fit 2024-08..2025-03  -> test 2025-04..2025-05
    fit 2024-08..2025-05  -> test 2025-06..2025-07     ... and so on

Every test window is genuinely unseen, every fold refits from scratch, and the
training set grows exactly as it would in production. Two properties this has
that a single split does not: ~10 independent test folds instead of 1, and
decay visible as a trend across folds rather than one before/after number.

Everything that could leak is refit per fold — per-constraint shadow-price
medians, rarity bands, and the wind median all come from the TRAIN window only.
The trailing 2 calendar months are reserved and never read (see memory:
ercot-holdout-rule).

The rule under test, fixed in advance from the earlier cuts:
    on hours DAM flags a RARE constraint at a shadow price ABOVE its own
    trailing median, hold that constraint's beta pair (long +beta nodes,
    short -beta nodes). Pair construction cancels the system DA premium.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import os
import pathlib
import statistics
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg  # noqa: E402

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"
CARDS = json.loads((REF / "constraint_cards.json").read_text())
SKIP = {"1025__B"}                     # unstable betas — negative_knowledge
TRAIN_MIN_MONTHS = 6
STEP_MONTHS = 2
RARE_MAX = 0.20                        # share of hours a constraint may bind


def month_add(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    return dt.date(y, m + 1, 1)


def stat(v):
    if len(v) < 30:
        return None
    m = statistics.fmean(v)
    sd = statistics.pstdev(v)
    se = sd / math.sqrt(len(v)) if sd else 0
    return m, (m / se if se else 0.0), len(v)


def shape(v):
    """Distribution, not just its centre.

    A mean hides the difference between a steady earner and a trade that wins
    small constantly then loses everything twice — which is precisely how the
    DART fade strategy showed a 62% hit rate while losing $54k/MW. Reported per
    fold so a fold carried by one lucky hour is visible as such.
    """
    if len(v) < 30:
        return None
    wins = [x for x in v if x > 0]
    losses = [x for x in v if x < 0]
    sv = sorted(v)
    tot = sum(v)
    best = max(v)
    return {
        "win_rate": round(100 * len(wins) / len(v), 1),
        "median": round(statistics.median(v), 3),
        "avg_win": round(statistics.fmean(wins), 3) if wins else 0.0,
        "avg_loss": round(statistics.fmean(losses), 3) if losses else 0.0,
        "worst": round(sv[0], 2),
        "p5": round(sv[int(0.05 * len(sv))], 2),
        "p95": round(sv[int(0.95 * len(sv))], 2),
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        "best_hour_share": round(100 * best / tot, 1) if tot > 0 else None,
    }


def main() -> int:
    pairs, allnodes = {}, set()
    for cname, card in CARDS.items():
        if cname in SKIP:
            continue
        pos = [x["node"] for x in card["exposure"]["sinks_when_binding"][:3]]
        neg = [x["node"] for x in card["exposure"]["sources_when_binding"][:3]]
        if pos and neg:
            pairs[cname] = (pos, neg)
            allnodes |= set(pos) | set(neg)
    allnodes = sorted(allnodes)

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=60) as c:
        c.execute("set statement_timeout='90min'")
        cur = c.cursor()
        cur.execute("select min(delivery_date), max(delivery_date) from dam_constraints")
        dlo, dhi = cur.fetchone()
        holdout_from = month_add(dhi.replace(day=1), -1)
        start = month_add(dlo.replace(day=1), 1)
        print(f"dam_constraints {dlo} .. {dhi}")
        print(f"usable through {holdout_from} (trailing 2 months reserved)")
        if month_add(start, TRAIN_MIN_MONTHS + STEP_MONTHS) > holdout_from:
            print("\n!! not enough DAM-constraint history for a walk-forward yet.")
            print("   Needs >= 8 months before the reserved holdout; rerun after backfill.")
            return 0

        cur.execute("""
            create temporary table dart as
            with rt as (select delivery_date d, delivery_hour he, settlement_point sp,
                               avg(price) rt
                          from rt_spp
                         where settlement_point = any(%s)
                           and delivery_date >= %s and delivery_date < %s
                         group by 1,2,3)
            select da.delivery_date d, da.hour_ending he, da.settlement_point sp,
                   rt.rt - da.price dart
              from dam_spp da
              join rt on rt.d=da.delivery_date and rt.he=da.hour_ending
                     and rt.sp=da.settlement_point
             where da.settlement_point = any(%s)
               and da.delivery_date >= %s and da.delivery_date < %s
        """, (allnodes, start, holdout_from, allnodes, start, holdout_from))
        cur.execute("select d, he, sp, dart from dart")
        D = collections.defaultdict(dict)
        for d, he, sp, v in cur.fetchall():
            D[(d, he)][sp] = float(v)
        print(f"loaded {len(D):,} node-hours")

        cur.execute("""select delivery_date, avg(actual_mw) from wind_power
                        where region='SystemWide' and actual_mw is not null
                          and delivery_date >= %s and delivery_date < %s
                        group by 1""", (start, holdout_from))
        wind = {d: float(w) for d, w in cur.fetchall()}

        flags = {}
        for cname in pairs:
            cur.execute("""select delivery_date, hour_ending, max(shadow_price)
                             from dam_constraints
                            where constraint_name=%s and shadow_price>0
                              and delivery_date >= %s and delivery_date < %s
                            group by 1,2""", (cname, start, holdout_from))
            flags[cname] = {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}

    folds = []
    train_end = month_add(start, TRAIN_MIN_MONTHS)
    print(f"\n{'fold':<5}{'train':<24}{'test':<20}{'rule $/MWh':>12}{'t':>7}"
          f"{'n':>8}{'baseline':>10}{'edge':>9}")
    i = 0
    while month_add(train_end, STEP_MONTHS) <= holdout_from:
        test_end = month_add(train_end, STEP_MONTHS)
        i += 1

        # --- fit: thresholds from TRAIN ONLY
        tr_hours = sum(1 for k in D if start <= k[0] < train_end)
        med, rare = {}, set()
        for cname, fh in flags.items():
            sps = [sp for (d, he), sp in fh.items() if start <= d < train_end]
            if not sps:
                continue
            med[cname] = statistics.median(sps)
            if len(sps) / max(tr_hours, 1) < RARE_MAX:
                rare.add(cname)

        def score(lo, hi):
            rule, base = [], []
            for cname, (pos, neg) in pairs.items():
                fh = flags[cname]
                m = med.get(cname)
                if m is None:
                    continue
                for key, prices in D.items():
                    if not (lo <= key[0] < hi):
                        continue
                    p = [prices[s] for s in pos if s in prices]
                    q = [prices[s] for s in neg if s in prices]
                    if not p or not q:
                        continue
                    val = statistics.fmean(p) - statistics.fmean(q)
                    sp = fh.get(key)
                    base.append(val)
                    if sp is not None and cname in rare and sp >= m:
                        rule.append(val)
            return rule, base

        r_test, b_test = score(train_end, test_end)
        s, bs = stat(r_test), stat(b_test)
        sh = shape(r_test)
        if s:
            folds.append({"fold": i, "train_end": str(train_end), "test_end": str(test_end),
                          "rule": round(s[0], 3), "t": round(s[1], 2), "n": s[2],
                          "baseline": round(bs[0], 3) if bs else None,
                          "edge": round(s[0] - (bs[0] if bs else 0), 3),
                          "shape": sh})
            print(f"{i:<5}{f'{start}..{train_end}':<24}{f'{train_end}..{test_end}':<20}"
                  f"{s[0]:>+12.3f}{s[1]:>7.2f}{s[2]:>8,}"
                  f"{(bs[0] if bs else 0):>+10.3f}{s[0]-(bs[0] if bs else 0):>+9.3f}")
            if sh:
                print(f"{'':5}  win {sh['win_rate']}%  med {sh['median']:+.3f}  "
                      f"avgW {sh['avg_win']:+.2f} avgL {sh['avg_loss']:+.2f}  "
                      f"worst {sh['worst']:+.1f}  PF {sh['profit_factor']}  "
                      f"best-hour {sh['best_hour_share']}% of P&L")
        else:
            print(f"{i:<5}{f'{start}..{train_end}':<24}{f'{train_end}..{test_end}':<20}"
                  f"{'too few flagged hours':>36}")
        train_end = test_end

    if folds:
        edges = [f["edge"] for f in folds]
        rules = [f["rule"] for f in folds]
        pos = sum(1 for e in edges if e > 0)
        m = statistics.fmean(edges)
        se = statistics.stdev(edges) / math.sqrt(len(edges)) if len(edges) > 1 else 0
        print("-" * 95)
        print(f"folds {len(folds)}   mean edge {m:+.3f} $/MWh   positive {pos}/{len(folds)}"
              f"   paired t {m/se:.2f}" if se else f"folds {len(folds)}   mean edge {m:+.3f}")
        if len(folds) >= 4:
            h1 = statistics.fmean(edges[:len(edges)//2])
            h2 = statistics.fmean(edges[len(edges)//2:])
            print(f"decay check: first half {h1:+.3f} -> second half {h2:+.3f} "
                  f"({h2-h1:+.3f})")
        shapes = [f["shape"] for f in folds if f.get("shape")]
        if shapes:
            print(f"\nTRADE SHAPE across folds:")
            print(f"  win rate      {statistics.fmean(s['win_rate'] for s in shapes):.1f}% "
                  f"(range {min(s['win_rate'] for s in shapes):.0f}-"
                  f"{max(s['win_rate'] for s in shapes):.0f})")
            pf = [s["profit_factor"] for s in shapes if s["profit_factor"]]
            if pf:
                print(f"  profit factor {statistics.fmean(pf):.2f} "
                      f"(>1.3 is tradeable, <1.1 is noise after costs)")
            print(f"  worst hour    {min(s['worst'] for s in shapes):+.1f} $/MWh")
            bh = [s["best_hour_share"] for s in shapes if s["best_hour_share"]]
            if bh:
                worst_conc = max(bh)
                print(f"  max single-hour share of a fold's P&L: {worst_conc:.0f}%"
                      f"{'  <-- LOTTERY TICKET, not a strategy' if worst_conc > 30 else ''}")
        json.dump(folds, open(REF / "walk_forward_folds.json", "w"), indent=1)
        print("wrote", REF / "walk_forward_folds.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
