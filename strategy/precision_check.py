#!/usr/bin/env python3
"""Hindsight precision check on the tuning months, with the paper-month model.

    python strategy/precision_check.py --months 2025-10,2025-11,2025-12,2026-01 [--tou PeakWD]

For each month: the month's own DAM injections (hindsight, as in the replay
pilot) on its own CRR model; every monitored element's 95th-percentile loading
under three views - base case on lines only (the pilot's view), base case on
lines and transformers, and worst of base case and every contingency on lines
and transformers. An element "bound" if a DAM constraint between its stations
had a shadow price in the month's TOU hours. Reports AUC (bound vs not) and the
share that bound among the top 25/50/100. Tuning months only - no paper month.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg

from strategy.common import REF
from strategy.paper_month import MON, N1, Mapper, compose, device_branches, injections, month_days
from strategy.replay_pilot import Grid, auc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", required=True)
    ap.add_argument("--tou", default="PeakWD")
    args = ap.parse_args()
    M = REF / "crr_models"
    for ym in args.months.split(","):
        y, m = map(int, ym.split("-"))
        tag = f"{y}.{MON[m - 1]}.Monthly.Auction"
        raw = next(M.glob(f"Common_{tag}_*_{args.tou}_Common_NetworkModel.RAW"))
        g = Grid(raw)
        mp = Mapper(g, raw)
        pairs = defaultdict(list)
        for n, b in enumerate(g.br):
            pairs[(min(b["i"], b["j"]), max(b["i"], b["j"]))].append((b["ckt"], n))
        mon = {}
        for r in csv.DictReader(
            open(next(M.glob(f"Common_MonitoredLinesAndTransformers_{tag}_*.CSV")))
        ):
            if r["TimeOfUse"] == args.tou:
                try:
                    rt = (
                        float(r["BaseCaseRating"]),
                        float(r["EmergencyRating"] or r["BaseCaseRating"]),
                    )
                except ValueError:
                    continue
                for n in device_branches(g, r["DeviceName"], pairs):
                    if rt[0]:
                        mon[n] = (rt, r["DeviceType"].upper().startswith("XF"))
        conts = defaultdict(set)
        for r in csv.DictReader(open(next(M.glob(f"Common_Contingencies_{tag}_*.CSV")))):
            conts[r["Contingency"]].update(device_branches(g, r["DeviceName"], pairs))
        idxs = sorted(mon)
        rates = np.array([mon[n][0][0] for n in idxs])
        erates = np.array([mon[n][0][1] for n in idxs])
        is_x = np.array([mon[n][1] for n in idxs])
        days = month_days(y, m)
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            c.execute("set statement_timeout='300s'")
            hours, P = injections(c, g, mp, days, args.tou)
            binds = c.execute(
                """select distinct from_station, to_station from dam_constraints
                    where delivery_date between %s and %s and hour_ending between 7 and 22 and shadow_price > 0""",
                (days[0], days[-1]),
            ).fetchall()
        bound = set()
        for fs, ts in binds:
            A = mp.sub.get(fs, set()) or (
                {b for b in g.idx if g.buses[b]["name"].upper().startswith(fs.upper())}
                if fs
                else set()
            )
            B = mp.sub.get(ts, set()) or (
                {b for b in g.idx if g.buses[b]["name"].upper().startswith(ts.upper())}
                if ts
                else set()
            )
            for n, br in enumerate(g.br):
                if (br["i"] in A and br["j"] in B) or (br["j"] in A and br["i"] in B):
                    bound.add(n)
        f0, gk, _c, _ = g.solver(frozenset())
        base = N1.__new__(N1)
        base.g, base.f, base.gkeep = g, f0, gk
        base.I = np.array([g.idx[b["i"]] for b in g.br])
        base.J = np.array([g.idx[b["j"]] for b in g.br])
        base.X = np.array([b["x"] for b in g.br])
        ix = np.array(idxs)
        L0 = np.zeros((len(hours), len(idxs)))
        FL = []
        for t, h in enumerate(hours):
            fl = base.flows(compose(P[h], "base"))
            FL.append(fl)
            L0[t] = np.abs(fl[ix]) / rates
        p0 = np.percentile(L0, 95, axis=0)
        pos_idx = {n: k for k, n in enumerate(idxs)}
        screen = [idxs[k] for k in np.argsort(-p0) if p0[k] >= 0.4][:2500]
        n1 = N1(g, screen, conts)
        sc = np.array([pos_idx[n] for n in screen])
        L1 = L0.copy()
        for t, fl in enumerate(FL):
            pc = np.abs(n1.post(fl)).max(axis=1) / erates[sc]
            L1[t, sc] = np.maximum(L1[t, sc], pc)
        p1 = np.percentile(L1, 95, axis=0)
        print(
            f"=== {ym}: monitored {len(idxs)} ({int(is_x.sum())} transformers); contingencies used "
            f"{len(n1.names)} ({n1.partial} partial, {n1.skipped} skipped)",
            flush=True,
        )
        for label, p95, sel in (
            ("base case, lines only (pilot view)", p0, ~is_x),
            ("base case, lines + transformers", p0, np.ones(len(idxs), bool)),
            ("with line trips, lines + transformers", p1, np.ones(len(idxs), bool)),
        ):
            ks = np.where(sel)[0]
            y_ = np.array([idxs[k] in bound for k in ks])
            v = p95[ks]
            rate = y_.mean()
            order = np.argsort(-v)
            tops = ", ".join(
                f"top {k}: {y_[order[:k]].mean():.0%} ({y_[order[:k]].mean() / rate:.1f}x)"
                for k in (25, 50, 100)
            )
            a = auc(list(v[y_]), list(v[~y_]))
            print(
                f"  {label:40s} bound {int(y_.sum())}/{len(ks)} ({rate:.1%}); AUC {a:.2f}; {tops}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
