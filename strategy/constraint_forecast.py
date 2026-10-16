#!/usr/bin/env python3
"""Constraint-level forecast (plan addendum, 16 Oct 2026): predict next month's
DAM binding constraints and their $, value paths through the model's shift
factors, and score both levels.

    python strategy/constraint_forecast.py --month 2026-01 [--n-random 300]
    python strategy/constraint_forecast.py --month 2026-02 --holdout --method F1

Forecasts (forward-valid, from data public at the sealed month's decision date):
  F0 persistence: $ per peak-weekday hour over the 100 days to asof
  F1 recency-weighted: last 30 / 31-60 / 61-100 days weighted 0.5 / 0.3 / 0.2
  F2 seasonal blend: half F0, half the same month one year earlier
  F3 physics-adjusted: F0 x clip(analog 95th-pct N-1 loading of the element, 0.5, 1.5)
  V5 ceiling: the delivery month's actual constraints and $ (hindsight), same directions
Constraint keys are (constraint name, contingency), mapped to the delivery
month's model branches by station; the binding direction comes from flows on
the latest 30 disclosed days (known at asof). Constraints without station
names (interface limits) are dropped. FEB 2026 runs only with --holdout and a
single --method, and writes a separate file.
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
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, REF, ROOT
from strategy.paper_month import (
    MIN_CLEAR,
    MON,
    N1,
    NODE_CAP,
    Mapper,
    device_branches,
    excluded,
    injections,
    month_days,
    ptdf_row,
)
from strategy.replay_pilot import Grid

load_dotenv(ROOT / ".env")
DEV = ("2025-11", "2025-12", "2026-01", "2026-03", "2026-05", "2026-07")
HOLDOUT = ("2026-02",)
TOU = "PeakWD"
METHODS = ("F0", "F1", "F2", "F3")


def spearman(x, y):
    if len(x) < 10:
        return None
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return round(float(np.corrcoef(rx, ry)[0, 1]), 3)


def tou_hours(d0, d1):
    return sum(
        1
        for k in range((d1 - d0).days + 1)
        for he in range(1, 25)
        if tou_of(d0 + timedelta(days=k), he) == TOU
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--n-random", type=int, default=300)
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--method", choices=METHODS)
    args = ap.parse_args()
    if args.month in HOLDOUT:
        if not (args.holdout and args.method):
            raise SystemExit("the holdout runs only with --holdout and one frozen --method")
        methods = (args.method,)
    elif args.month in DEV:
        methods = METHODS
    else:
        raise SystemExit(
            f"{args.month} is neither a development month {DEV} nor the holdout {HOLDOUT}"
        )
    man = json.loads(
        (ARCHIVE / "out" / "sealed" / f"paper_{args.month}_{TOU}" / "manifest.json").read_text()
    )
    asof = date.fromisoformat(man["asof"])
    y, m = map(int, args.month.split("-"))
    dmonth = month_days(y, m)
    analog = month_days(y - 1, m)
    recent = [date.fromisoformat(man["recent"][0]) + timedelta(days=k) for k in range(30)]
    hist0 = asof - timedelta(days=100)
    prior = man["prior_auctions"]
    tag = f"{y}.{MON[m - 1]}.Monthly.Auction"
    M = REF / "crr_models"
    raw = next(M.glob(f"Common_{tag}_*_{TOU}_Common_NetworkModel.RAW"))
    g = Grid(raw)
    mp = Mapper(g, raw)
    pairs = defaultdict(list)
    for n, b in enumerate(g.br):
        pairs[(min(b["i"], b["j"]), max(b["i"], b["j"]))].append((b["ckt"], n))
    mon_br = {}
    for r in csv.DictReader(
        open(next(M.glob(f"Common_MonitoredLinesAndTransformers_{tag}_*.CSV")))
    ):
        if r["TimeOfUse"] == TOU:
            try:
                rt = (
                    float(r["BaseCaseRating"]),
                    float(r["EmergencyRating"] or r["BaseCaseRating"]),
                )
            except ValueError:
                continue
            for n in device_branches(g, r["DeviceName"], pairs):
                if rt[0]:
                    mon_br[n] = rt
    conts = defaultdict(set)
    for r in csv.DictReader(open(next(M.glob(f"Common_Contingencies_{tag}_*.CSV")))):
        conts[r["Contingency"]].update(device_branches(g, r["DeviceName"], pairs))

    def stations(fs, ts):
        A = mp.sub.get(fs, set()) or (
            {b for b in g.idx if g.buses[b]["name"].upper().startswith(fs.upper())} if fs else set()
        )
        B = mp.sub.get(ts, set()) or (
            {b for b in g.idx if g.buses[b]["name"].upper().startswith(ts.upper())} if ts else set()
        )
        return [
            n
            for n, br in enumerate(g.br)
            if (br["i"] in A and br["j"] in B) or (br["j"] in A and br["i"] in B)
        ]

    st_cache = {}

    def br_of(fs, ts):
        if (fs, ts) not in st_cache:
            st_cache[(fs, ts)] = stations(fs, ts) if fs else []
        return st_cache[(fs, ts)]

    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        drop = defaultdict(set)
        for res, s, e, red, mx in c.execute(
            """select coalesce(unit_code, resource_name), outage_start::date,
                coalesce(planned_end::date, outage_start::date), reduction_mw, max_mw from resource_outages
                where report_date <= %s and outage_start::date <= %s and coalesce(planned_end::date, outage_start::date) >= %s""",
            (asof, dmonth[-1], dmonth[0]),
        ):
            if red and mx and float(red) >= 0.5 * float(mx):
                for d_del, d_an in zip(dmonth, analog, strict=False):
                    if s <= d_del <= e:
                        drop[d_an].add(res)
        print("injections: analog / recent ...", flush=True)
        ah, AP = injections(c, g, mp, analog, TOU, drop, asof)
        rh, RP = injections(c, g, mp, recent, TOU, None, asof)

        def constraint_rows(d0, d1):
            return c.execute(
                """select constraint_name, contingency, from_station, to_station, delivery_date, hour_ending, shadow_price
                    from dam_constraints where delivery_date between %s and %s and shadow_price > 0""",
                (d0, d1),
            ).fetchall()

        hist_rows = constraint_rows(hist0, asof - timedelta(days=1))
        seas_rows = constraint_rows(analog[0], analog[-1])
        next_rows = constraint_rows(dmonth[0], dmonth[-1])
        pclr = {
            sp: float(v)
            for sp, v in c.execute(
                "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use=%s",
                (prior[-1], TOU),
            )
        }
        clr = {
            sp: float(v)
            for sp, v in c.execute(
                "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use=%s",
                (f"{MON[m - 1]}{y}Monthly", TOU),
            )
        }
        cands = c.execute(
            "select distinct source, sink from crr_awards where auction_name = any(%s) and hedge_type='OBL' "
            "and bid_type='BUY' and time_of_use=%s",
            (prior, TOU),
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
                (nodes[i : i + 100], dmonth[0], dmonth[-1]),
            ):
                if tou_of(dd, he) == TOU:
                    pr[sp][(dd, he)] = float(p)
    nh = len({h for v in pr.values() for h in v})

    def payout(a, b):
        v = [pr[b][h] - pr[a][h] for h in pr[a] if h in pr[b]]
        return statistics.mean(v) if len(v) >= 0.9 * nh else None

    univ = [(a, b, ec, payout(a, b)) for a, b, ec in univ]
    univ = [u for u in univ if u[3] is not None]

    # ---------- constraint $ by key over windows ----------
    def dollars(rows, d0=None, d1=None):
        out, brs = defaultdict(float), {}
        for name, cont, fs, ts, d, he, spv in rows:
            if tou_of(d, he) != TOU or (d0 and d < d0) or (d1 and d > d1):
                continue
            b = br_of(fs, ts)
            if not b:
                continue
            out[(name, cont)] += float(spv)
            brs[(name, cont)] = b
        return out, brs

    a1 = asof - timedelta(days=1)
    w30 = (asof - timedelta(days=30), a1)
    w60 = (asof - timedelta(days=60), asof - timedelta(days=31))
    w100 = (hist0, asof - timedelta(days=61))
    h_all, br_hist = dollars(hist_rows)
    h30, _ = dollars(hist_rows, *w30)
    h60, _ = dollars(hist_rows, *w60)
    h100, _ = dollars(hist_rows, *w100)
    seas, br_seas = dollars(seas_rows)
    truth, br_next = dollars(next_rows)
    H_all, H30, H60, H100 = tou_hours(hist0, a1), tou_hours(*w30), tou_hours(*w60), tou_hours(*w100)
    H_seas = tou_hours(analog[0], analog[-1])
    keys_branch = {**br_seas, **br_hist, **br_next}
    print(
        f"universe {len(univ)} paths; constraint keys: history {len(h_all)}, seasonal {len(seas)}, actual {len(truth)}",
        flush=True,
    )

    # ---------- flows: N-1 screen on every branch any constraint maps to ----------
    flows_eng = N1.__new__(N1)
    f0_, gk_, _, _ = g.solver(frozenset())
    flows_eng.g, flows_eng.f, flows_eng.gkeep = g, f0_, gk_
    flows_eng.I = np.array([g.idx[b["i"]] for b in g.br])
    flows_eng.J = np.array([g.idx[b["j"]] for b in g.br])
    flows_eng.X = np.array([b["x"] for b in g.br])

    def balanced(parts):
        other, _wcap, gas, dropped, shape = parts
        D, G = dropped.sum(), gas.sum()
        g2 = gas * (1 + D / G) if D > 0 and G > 0 else gas
        inj = other + g2
        return inj - inj.sum() * shape

    screen = sorted({n for b in keys_branch.values() for n in b})[:4000]
    n1 = N1(g, screen, conts)
    srow = {n: r for r, n in enumerate(n1.screen)}
    cidx = {nm: k for k, nm in enumerate(n1.names)}

    def post_flow(fl, n, ci):
        if ci is None or ci < 0 or n not in srow:
            return fl[n]
        st = n1.starts[ci]
        K = n1.members[ci]
        return fl[n] + float(np.dot(n1.W[srow[n], st : st + len(K)], fl[np.array(K)]))

    rec_flows = [n1.flows(balanced(RP[h])) for h in rh]
    an_flows = [n1.flows(balanced(AP[h])) for h in ah]
    sign_cache = {}

    def sign_of(n, ci):
        if (n, ci) not in sign_cache:
            v = np.median([post_flow(fl, n, ci) for fl in rec_flows]) if rec_flows else 0.0
            if abs(v) < 1e-6:
                v = np.median([post_flow(fl, n, ci) for fl in an_flows])
            sign_cache[(n, ci)] = 1.0 if v >= 0 else -1.0
        return sign_cache[(n, ci)]

    load95 = {}

    def analog_loading(n, ci):
        if (n, ci) not in load95:
            rate = (
                (mon_br.get(n, (None, None))[1 if ci is not None and ci >= 0 else 0])
                or g.br[n].get("rate")
                or None
            )
            if not rate:
                load95[(n, ci)] = 1.0
            else:
                load95[(n, ci)] = float(
                    np.percentile([abs(post_flow(fl, n, ci)) / rate for fl in an_flows], 95)
                )
        return load95[(n, ci)]

    base_rows = {}

    def brow(n):
        if n not in base_rows:
            base_rows[n] = ptdf_row(g, n)
        return base_rows[n]

    row_cache = {}

    def row(n, ci):
        if (n, ci) in row_cache:
            return row_cache[(n, ci)]
        r = brow(n)
        if ci is not None and ci >= 0 and n in srow:
            st = n1.starts[ci]
            K = n1.members[ci]
            w = n1.W[srow[n], st : st + len(K)]
            r = r + sum(float(wk) * brow(k) for wk, k in zip(w, K, strict=True))
        row_cache[(n, ci)] = r
        return r

    nodes_ = sorted({x for a, b, _, _ in univ for x in (a, b)})
    spread = {sp: mp.spread(sp) for sp in nodes_}

    def path_values(fc):
        """fc: {(name, cont): $ per hour} -> {(src, snk): value}"""
        elems = []
        for key, val in fc.items():
            if val <= 0:
                continue
            _name, cont = key
            brs = keys_branch.get(key, [])
            if not brs:
                continue
            ci = cidx.get(cont, -1) if cont else -1
            for n in brs:
                elems.append((row(n, ci), sign_of(n, ci), val / len(brs)))
        if not elems:
            return {}
        R = np.stack([r for r, _, _ in elems])  # elems x buses
        sv = np.array([s * v for _, s, v in elems])
        weighted = sv @ R  # value per unit injection at each bus
        node_v = {}
        for sp, w in spread.items():
            node_v[sp] = None if not w else sum(weighted[g.idx[b]] * f for b, f in w.items())
        return {
            (a, b): node_v[a] - node_v[b]
            for a, b, _, _ in univ
            if node_v[a] is not None and node_v[b] is not None
        }

    def forecast(method):
        f = {}
        for k in set(h_all) | set(seas):
            f0 = h_all.get(k, 0) / max(H_all, 1)
            if method == "F0":
                f[k] = f0
            elif method == "F1":
                f[k] = (
                    0.5 * h30.get(k, 0) / max(H30, 1)
                    + 0.3 * h60.get(k, 0) / max(H60, 1)
                    + 0.2 * h100.get(k, 0) / max(H100, 1)
                )
            elif method == "F2":
                f[k] = 0.5 * f0 + 0.5 * seas.get(k, 0) / max(H_seas, 1)
            elif method == "F3":
                brs = keys_branch.get(k, [])
                ci = cidx.get(k[1], -1) if k[1] else -1
                lf = statistics.mean(analog_loading(n, ci) for n in brs) if brs else 1.0
                f[k] = f0 * min(max(lf, 0.5), 1.5)
        return {k: v for k, v in f.items() if v > 0}

    actual = {k: v / max(nh, 1) for k, v in truth.items()}
    tot_actual = sum(actual.values()) or 1.0

    def evaluate(label, fc):
        res = {"forecast": label}
        keys = sorted(set(fc) | set(actual))
        res["constraint_rho"] = spearman(
            [fc.get(k, 0) for k in keys], [actual.get(k, 0) for k in keys]
        )
        top50 = sorted(fc, key=lambda k: -fc[k])[:50]
        res["top50_share_actual"] = round(sum(actual.get(k, 0) for k in top50) / tot_actual, 3)
        values = path_values(fc)
        rows_ = [
            (values[(a, b)], ec, clr[a] - clr[b], p) for a, b, ec, p in univ if (a, b) in values
        ]
        v = np.array([r[0] for r in rows_])
        ec = np.array([r[1] for r in rows_])
        ac = np.array([r[2] for r in rows_])
        py = np.array([r[3] for r in rows_])
        edge, ex = v - ec, py - ac
        res["paths"] = len(rows_)
        res["rho_value_payout"] = spearman(v, py)
        res["rho_edge_excess"] = spearman(edge, ex)
        big = np.abs(py) > 0.25
        res["direction_hit"] = (
            round(float(((v[big] > 0) == (py[big] > 0)).mean()), 3) if big.any() else None
        )
        bk = sorted(
            (
                (vv - e, a, b, e, vv)
                for a, b, e, _p in univ
                for vv in [values.get((a, b))]
                if vv is not None and vv >= 1.5 * e and e <= 3.0
            ),
            key=lambda t: (-t[0], t[1], t[2]),
        )
        sel, ns, nk = [], defaultdict(int), defaultdict(int)
        for _e, a, b, e, vv in bk:
            if ns[a] < NODE_CAP and nk[b] < NODE_CAP:
                sel.append((a, b, e, vv / 1.5))
                ns[a] += 1
                nk[b] += 1
                if len(sel) == 60:
                    break
        P_ = {(a, b): p for a, b, _e, p in univ}

        def score(s):
            cost = gain = 0.0
            for a, b, _e, lim in s:
                acp = clr[a] - clr[b]
                if lim >= acp:
                    cost += 5 * nh * acp
                    gain += 5 * nh * P_[(a, b)]
            return gain - cost

        res["book_positions"] = len(sel)
        res["book_profit"] = round(score(sel))
        if sel:
            lr = statistics.median(lim / e for _a, _b, e, lim in sel)
            pool = [(a, b, e) for a, b, e, _p in univ if e <= 3.0]
            rng = random.Random(f"{args.month}|{label}")
            sims = []
            for _ in range(args.n_random):
                order = rng.sample(pool, len(pool))
                s2, ns2, nk2 = [], defaultdict(int), defaultdict(int)
                for a, b, e in order:
                    if ns2[a] < NODE_CAP and nk2[b] < NODE_CAP:
                        s2.append((a, b, e, e * lr))
                        ns2[a] += 1
                        nk2[b] += 1
                        if len(s2) == len(sel):
                            break
                sims.append(score(s2))
            sims = np.array(sims)
            res["random_median"] = round(float(np.median(sims)))
            res["book_percentile"] = round(float((sims < res["book_profit"]).mean() * 100), 1)
        else:
            res["book_percentile"] = None
        print("  " + json.dumps(res), flush=True)
        return res, sel

    results, books = [], {}
    for meth in methods:
        r, sel = evaluate(meth, forecast(meth))
        results.append(r)
        books[meth] = sel
    if args.month not in HOLDOUT:
        results.append(evaluate("V5 ceiling", actual)[0])
    outd = ARCHIVE / "out" / "experiment"
    outd.mkdir(parents=True, exist_ok=True)
    name = f"constraint_{args.month}" + ("_holdout" if args.month in HOLDOUT else "") + ".json"
    (outd / name).write_text(
        json.dumps(
            dict(
                month=args.month,
                asof=str(asof),
                universe=len(univ),
                results=results,
                books={
                    k: [
                        dict(source=a, sink=b, exp_clear=round(e, 4), limit=round(lim, 2))
                        for a, b, e, lim in v
                    ]
                    for k, v in books.items()
                },
            ),
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
