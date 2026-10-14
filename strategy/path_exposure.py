#!/usr/bin/env python3
"""Empirical path -> constraint exposure, without the network model.

    python strategy/path_exposure.py --paths <csv with source,sink> [--months 12]

For each path, the daily peak spread (node_day_spread: sink - source) is
regressed on the daily peak-hour DAM shadow-price totals of the top constraints
(dam_constraints, HE7-22), with ridge shrinkage because constraints co-bind.
The coefficient times the constraint's mean daily shadow over the window is
that constraint's contribution to the path's value ($/MWh). This is what a
relief adjustment subtracts when a constraint is upgraded away.

Writes REF/path_exposure.json {"SRC|SNK": {"value": v, "contrib": {constraint: $/MWh}, "r2": r2}}.
Read-only against the database.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import REF, ROOT

load_dotenv(ROOT / ".env")
TOP = 150
RIDGE = 5.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", required=True)
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--end", default=None, help="last day of the fit window (default: latest data)")
    args = ap.parse_args()
    paths = sorted({(r["source"], r["sink"]) for r in csv.DictReader(open(args.paths))})
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        end = date.fromisoformat(args.end) if args.end else c.execute("select max(delivery_date) from dam_constraints").fetchone()[0]
        start = end - timedelta(days=30 * args.months)
        top = [r[0] for r in c.execute("""select constraint_name from dam_constraints
               where delivery_date between %s and %s and hour_ending between 7 and 22
               group by 1 order by sum(shadow_price) desc limit %s""", (start, end, TOP))]
        S = defaultdict(dict)
        for n, d, s in c.execute("""select constraint_name, delivery_date, sum(shadow_price) from dam_constraints
               where delivery_date between %s and %s and hour_ending between 7 and 22 and constraint_name = any(%s)
               group by 1, 2""", (start, end, top)):
            S[n][d] = float(s or 0) / 16.0  # mean per peak hour
        nodes = sorted({n for p in paths for n in p})
        sp = defaultdict(dict)
        for n, d, s in c.execute("""select settlement_point, delivery_date, spread from node_day_spread
               where settlement_point = any(%s) and delivery_date between %s and %s""", (nodes, start, end)):
            sp[n][d] = float(s)
    days = sorted({d for v in sp.values() for d in v})
    X = np.array([[S[n].get(d, 0.0) for n in top] for d in days])
    mu = X.mean(axis=0)
    di = {d: i for i, d in enumerate(days)}
    out = {}
    for src, snk in paths:
        dd = [d for d in days if d in sp[src] and d in sp[snk]]
        if len(dd) < 120:
            continue
        idx = [di[d] for d in dd]
        Xi = X[idx]
        y = np.array([sp[snk][d] - sp[src][d] for d in dd])
        Xc, yc = Xi - Xi.mean(axis=0), y - y.mean()
        beta = np.linalg.solve(Xc.T @ Xc + RIDGE * len(dd) * np.eye(len(top)) * 1e-3 + 1e-9 * np.eye(len(top)), Xc.T @ yc)
        fit = Xc @ beta
        r2 = 1 - float(np.sum((yc - fit) ** 2) / max(np.sum(yc ** 2), 1e-9))
        contrib = {top[j]: round(float(beta[j] * mu[j]), 4) for j in range(len(top)) if abs(beta[j] * mu[j]) >= 0.01}
        out[f"{src}|{snk}"] = dict(value=round(float(y.mean()), 4), r2=round(r2, 3),
                                   contrib=dict(sorted(contrib.items(), key=lambda x: -abs(x[1]))[:12]))
    json.dump(dict(window=[str(start), str(end)], constraints=top, paths=out), open(REF / "path_exposure.json", "w"))
    r2s = sorted(v["r2"] for v in out.values())
    print(f"paths fitted {len(out)} of {len(paths)}; window {start}..{end}; R^2 median {r2s[len(r2s)//2]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
