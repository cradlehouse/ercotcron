#!/usr/bin/env python3
"""Injection experiment (plan addendum, 16 Oct 2026): does better injection
data rescue the physics? Only the injections change between variants.

    python strategy/injection_experiment.py --month 2026-01 [--n-random 500]

Uses the sealed month's manifest for its decision date, analog, recent window,
history window and prior auctions. Everything else - the delivery month's CRR
model, monitored elements, contingency list, N-1 screening, 100-day binding
history used for element values, hot-never filter, candidate universe,
expected clearing and scoring - is identical across:

  V1 year-ago injections (the builder's baseline)
  V2 V1 + structural drift known at asof (zonal load growth, fleet changes)
  V3 V2 + delivery-month weather (day-ahead zonal load, wind, solar by hour)
  V4 the delivery month's actual DAM injections (hindsight)
  V5 actual DAM binding constraints and shadow prices through the model's
     shift factors (hindsight; tests path mapping and value conversion)

Writes ARCHIVE/out/experiment/injection_<month>.json. Development months
only; refuses FEB 2026.
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
    HOT,
    MIN_CLEAR,
    MON,
    N1,
    NODE_CAP,
    TOPK,
    ZONE,
    Mapper,
    device_branches,
    excluded,
    injections,
    month_days,
    ptdf_row,
)
from strategy.replay_pilot import Grid, auc

load_dotenv(ROOT / ".env")
DEV = ("2025-11", "2025-12", "2026-01", "2026-03", "2026-05", "2026-07")
TOU = "PeakWD"
ZONES = ("Houston", "North", "South", "West")


def spearman(x, y):
    if len(x) < 10:
        return None
    rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
    return round(float(np.corrcoef(rx, ry)[0, 1]), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--n-random", type=int, default=500)
    args = ap.parse_args()
    if args.month not in DEV:
        raise SystemExit(f"{args.month} is not a designated development month {DEV}")
    man = json.loads(
        (ARCHIVE / "out" / "sealed" / f"paper_{args.month}_{TOU}" / "manifest.json").read_text()
    )
    asof = date.fromisoformat(man["asof"])
    y, m = map(int, args.month.split("-"))
    dmonth = month_days(y, m)
    analog = month_days(y - 1, m)
    recent = [date.fromisoformat(man["recent"][0]) + timedelta(days=k) for k in range(30)]
    hist0 = date.fromisoformat(man["history_window"][0])
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
    idxs = sorted(mon_br)
    ix = np.array(idxs)
    rates = np.array([mon_br[n][0] for n in idxs])
    erates = np.array([mon_br[n][1] for n in idxs])
    conts = defaultdict(set)
    for r in csv.DictReader(open(next(M.glob(f"Common_Contingencies_{tag}_*.CSV")))):
        conts[r["Contingency"]].update(device_branches(g, r["DeviceName"], pairs))
    zmask = {}
    for zn in ZONES:
        mk = np.zeros(len(g.ids), dtype=bool)
        for lz, bs in mp.lz.items():
            if ZONE.get(lz) == zn:
                for b in bs:
                    mk[g.idx[b]] = True
        zmask[zn] = mk
    nb = len(g.ids)

    def spread_vec(vec, sp, mw):
        w = mp.spread(sp)
        if w and mw:
            for b, f in w.items():
                vec[g.idx[b]] += mw * f

    def fc_by_he(c, product, series, days, edition_rule):
        """mean forecast per hour-ending over days (edition posted the day before delivery)."""
        acc = defaultdict(list)
        for d, vals in c.execute(
            """select delivery_date, vals from ercot_forecast_vintages where product=%s and series=%s
                and delivery_date between %s and %s and posted_at::date = delivery_date - 1""",
            (product, series, min(days), max(days)),
        ):
            if d in days and vals:
                for k, v in enumerate(vals):
                    if v is not None:
                        acc[k + 1].append(float(v))
        return {he: statistics.mean(v) for he, v in acc.items()}

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
        print("injections: analog / recent / actual ...", flush=True)
        ah, AP = injections(c, g, mp, analog, TOU, drop, asof)
        rh, RP = injections(c, g, mp, recent, TOU, None, asof)
        dh, DP = injections(c, g, mp, dmonth, TOU, None, None)  # V4: hindsight
        # fleet change known at asof: resources seen in the 90 days to asof-60
        f0, f1 = asof - timedelta(days=150), asof - timedelta(days=61)
        fleet = {
            r
            for (r,) in c.execute(
                "select distinct resource from dam_resource_awards where delivery_date between %s and %s",
                (f0, f1),
            )
        }
        an_set = {
            r
            for (r,) in c.execute(
                "select distinct resource from dam_resource_awards where delivery_date between %s and %s",
                (analog[0], analog[-1]),
            )
        }
        adds = defaultdict(lambda: np.zeros(nb))  # by hour-ending
        for d, res, sp, arr in c.execute(
            """select delivery_date, resource, settlement_point, awarded_mw from dam_resource_awards
                where delivery_date between %s and %s""",
            (recent[0], recent[-1]),
        ):
            if res in an_set:
                continue
            for k, v in enumerate(arr):
                if tou_of(d, k + 1) == TOU:
                    if v:
                        spread_vec(adds[k + 1], sp, v)
        ndays_recent = (
            len({d for d in recent if any(tou_of(d, he) == TOU for he in range(1, 25))}) or 1
        )
        adds = {he: v / ndays_recent for he, v in adds.items()}
        removes = {h: np.zeros(nb) for h in ah}
        solar = {h: np.zeros(nb) for h in ah}
        hs = set(ah)
        n_removed = set()
        for d, res, rt, sp, arr in c.execute(
            """select delivery_date, resource, resource_type, settlement_point, awarded_mw from dam_resource_awards
                where delivery_date between %s and %s""",
            (analog[0], analog[-1]),
        ):
            if res in drop.get(d, ()):
                continue
            gone = res not in fleet
            for k, v in enumerate(arr):
                if (d, k + 1) in hs and v:
                    if gone:
                        spread_vec(removes[(d, k + 1)], sp, v)
                        n_removed.add(res)
                    if rt == "PVGR":
                        spread_vec(solar[(d, k + 1)], sp, v)
        n_added = len(
            {
                r
                for (r,) in c.execute(
                    "select distinct resource from dam_resource_awards where delivery_date between %s and %s",
                    (recent[0], recent[-1]),
                )
            }
            - an_set
        )
        # zonal growth known at asof (V2) and delivery-month weather (V3)
        growth = {}
        for z in ZONES:
            now = fc_by_he(
                c, "NP3-560-CD", z, [asof - timedelta(days=k) for k in range(1, 31)], None
            )
            then = fc_by_he(
                c, "NP3-560-CD", z, [asof - timedelta(days=365 + k) for k in range(1, 31)], None
            )
            a, b = (
                statistics.mean(now.values()) if now else None,
                statistics.mean(then.values()) if then else None,
            )
            growth[z] = a / b if a and b else 1.0
        wx_load = {}
        for z in ZONES:
            dl, al = (
                fc_by_he(c, "NP3-560-CD", z, dmonth, None),
                fc_by_he(c, "NP3-560-CD", z, analog, None),
            )
            wx_load[z] = {he: dl[he] / al[he] for he in dl if al.get(he)}
        wd = fc_by_he(c, "NP4-742-CD", "STWPF_SYSTEM_WIDE", dmonth, None)
        wa = fc_by_he(c, "NP4-742-CD", "STWPF_SYSTEM_WIDE", analog, None)
        sd = fc_by_he(c, "NP4-745-CD", "STPPF_SYSTEM_WIDE", dmonth, None)
        sa = fc_by_he(c, "NP4-745-CD", "STPPF_SYSTEM_WIDE", analog, None)
        wind_delta = {he: wd[he] - wa[he] for he in wd if he in wa}
        solar_ratio = {he: sd[he] / sa[he] for he in sd if he in sa and sa[he] > 50}
        # history (identical across variants)
        binds = c.execute(
            """select constraint_name, from_station, to_station, from_kv, sum(shadow_price) from dam_constraints
                where delivery_date between %s and %s and hour_ending between 7 and 22 group by 1,2,3,4""",
            (hist0, asof - timedelta(days=1)),
        ).fetchall()
        dbind = c.execute(
            """select constraint_name, contingency, from_station, to_station, delivery_date, hour_ending, shadow_price
                from dam_constraints where delivery_date between %s and %s""",
            (dmonth[0], dmonth[-1]),
        ).fetchall()
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
    print(
        f"universe {len(univ)} paths; removed units {len(n_removed)}, added units {n_added}; "
        f"growth {', '.join(f'{z} {v:.3f}' for z, v in growth.items())}",
        flush=True,
    )

    # ---------- element values from history and delivery-month truth ----------
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
            st_cache[(fs, ts)] = stations(fs, ts)
        return st_cache[(fs, ts)]

    hist_hours = sum(
        1
        for k in range((asof - hist0).days)
        for he in range(1, 25)
        if tou_of(hist0 + timedelta(days=k), he) == TOU
    )
    bound_val = defaultdict(float)
    for _n, fs, ts, _kv, spv in binds:
        for n in br_of(fs, ts):
            bound_val[n] += float(spv or 0) / max(hist_hours, 1)
    pos = {n for n in bound_val if n in mon_br}
    med = statistics.median([v for v in bound_val.values() if v > 0]) if bound_val else 0.0
    next_dollars = defaultdict(float)
    truth = defaultdict(float)  # (constraint, contingency) -> $ in TOU hours
    truth_br = {}
    for name, cont, fs, ts, d, he, spv in dbind:
        if tou_of(d, he) != TOU or not spv:
            continue
        brs = br_of(fs, ts)
        for n in brs:
            next_dollars[n] += float(spv)
        truth[(name, cont)] += float(spv)
        truth_br[(name, cont)] = brs
    tot_next = sum(next_dollars.values()) or 1.0

    # ---------- injection variants ----------
    def base_parts(parts):
        other, wcap, gas, dropped, shape = parts
        D, G = dropped.sum(), gas.sum()
        g2 = gas * (1 + D / G) if D > 0 and G > 0 else gas
        return other + g2, g2, wcap, shape

    def variant(parts, h, v):
        inj, g2, wcap, shape = base_parts(parts)
        if v == 1:
            return inj - inj.sum() * shape
        L0 = inj.sum()
        he = h[1]
        inj = inj - removes[h] + adds.get(he, 0)
        if v == 3:
            wcs = wcap.sum()
            if wcs > 0 and he in wind_delta:
                inj = inj + wind_delta[he] * wcap / wcs
            if he in solar_ratio:
                inj = inj + (solar_ratio[he] - 1.0) * solar[h]
        f = {z: (wx_load[z].get(he, 1.0) if v == 3 else growth[z]) for z in ZONES}
        fac = np.ones(nb)
        for z in ZONES:
            fac[zmask[z]] = f[z]
        shape2 = shape * fac
        mass = shape2.sum()
        Lnew = L0 * mass if mass > 0 else L0
        shape2 = shape2 / mass if mass > 0 else shape
        G = g2.sum()
        if G > 0:
            inj = inj + max(Lnew - inj.sum(), -0.8 * G) / G * g2
        return inj - inj.sum() * shape2

    flows_eng = N1.__new__(N1)
    f0_, gk_, _, _ = g.solver(frozenset())
    flows_eng.g, flows_eng.f, flows_eng.gkeep = g, f0_, gk_
    flows_eng.I = np.array([g.idx[b["i"]] for b in g.br])
    flows_eng.J = np.array([g.idx[b["j"]] for b in g.br])
    flows_eng.X = np.array([b["x"] for b in g.br])
    pos_idx = {n: k for k, n in enumerate(idxs)}

    def vectors(v):
        if v == 4:
            return dh, {h: variant(DP[h], h, 1) for h in dh}
        return ah, {h: variant(AP[h], h, v) for h in ah}

    # screening set: union over variants of p95 base loading >= 0.4, plus history
    base_flows = {}
    keep = set(pos)
    for v in (1, 2, 3, 4):
        hours, P = vectors(v)
        L = np.array([np.abs(flows_eng.flows(P[h])[ix]) / rates for h in hours])
        base_flows[v] = (hours, P)
        p95 = np.percentile(L, 95, axis=0)
        keep |= {idxs[k] for k in np.argsort(-p95)[:2500] if p95[k] >= 0.4}
    screen = sorted(keep & set(mon_br))[:3000]
    n1 = N1(g, screen, conts)
    sc = np.array([pos_idx[n] for n in n1.screen])
    er = erates[sc].astype(np.float32)[:, None]
    print(f"screen {len(screen)} x {len(n1.names)} contingencies", flush=True)

    def loading(hours, P):
        L = np.zeros((len(hours), len(idxs)))
        S = np.zeros((len(hours), len(idxs)))
        worst = np.full((len(hours), len(sc)), -1, dtype=np.int32)
        for t, h in enumerate(hours):
            fl = n1.flows(P[h])
            fm = fl[ix]
            L[t], S[t] = np.abs(fm) / rates, np.sign(fm)
            pc = n1.post(fl)
            ld = np.abs(pc) / er
            k = ld.argmax(axis=1)
            lk = ld[np.arange(len(sc)), k]
            better = lk > L[t, sc]
            L[t, sc] = np.where(better, lk, L[t, sc])
            S[t, sc] = np.where(better, np.sign(pc[np.arange(len(sc)), k]), S[t, sc])
            worst[t] = np.where(better, k, -1)
        mode = {n: int(np.bincount(worst[:, r] + 1).argmax()) - 1 for r, n in enumerate(n1.screen)}
        return L, S, mode

    RL, _RS, _ = loading(rh, {h: variant(RP[h], h, 1) for h in rh})
    r95 = np.percentile(RL, 95, axis=0)
    hot_never = {idxs[k] for k in range(len(idxs)) if r95[k] >= HOT and idxs[k] not in pos}

    base_rows = {}

    def brow(n):
        if n not in base_rows:
            base_rows[n] = ptdf_row(g, n)
        return base_rows[n]

    srow = {n: r for r, n in enumerate(n1.screen)}

    def row(n, ci):
        r = brow(n)
        if ci is not None and ci >= 0 and n in srow:
            st = n1.starts[ci]
            K = n1.members[ci]
            w = n1.W[srow[n], st : st + len(K)]
            r = r + sum(float(wk) * brow(k) for wk, k in zip(w, K, strict=True))
        return r

    def sp_val(sp, vec):
        w = mp.spread(sp)
        return None if not w else sum(vec[g.idx[b]] * f for b, f in w.items())

    def path_values(elems):
        """elems: [(row vector, sign, $ value)] -> {(src, snk): value}"""
        out = {}
        nodes_ = sorted({x for a, b, _, _ in univ for x in (a, b)})
        pv = {}
        for sp in nodes_:
            vals = [sp_val(sp, r) for r, _, _ in elems]
            pv[sp] = None if any(v is None for v in vals) else np.array(vals)
        sv = np.array([s * v for _, s, v in elems])
        for a, b, _, _ in univ:
            if pv[a] is not None and pv[b] is not None:
                out[(a, b)] = float(np.dot(sv, pv[a] - pv[b]))
        return out

    rng_seed = f"{args.month}|inj"

    def evaluate(label, values, p95=None, pred=None):
        res = {"variant": label}
        if pred is not None:
            top = [n for n, _, _, _ in pred]
            res["bound_top100"] = sum(1 for n in top if n in next_dollars)
            res["dollars_caught"] = round(
                sum(next_dollars.get(n, 0) for n in set(top)) / tot_next, 3
            )
            res["new_binders"] = sum(1 for n in top if n in next_dollars and n not in pos)
        if p95 is not None:
            y_ = np.array([n in next_dollars for n in idxs])
            res["auc_p95"] = round(auc(list(p95[y_]), list(p95[~y_])) or 0, 3)
        rows_ = [
            (values[(a, b)], ec, ac, p)
            for a, b, ec, p in univ
            if (a, b) in values
            for ac in [clr[a] - clr[b]]
        ]
        v = np.array([r[0] for r in rows_])
        ec = np.array([r[1] for r in rows_])
        ac = np.array([r[2] for r in rows_])
        py = np.array([r[3] for r in rows_])
        edge, ex = v - ec, py - ac
        res["paths"] = len(rows_)
        res["rho_value_payout"] = spearman(v, py)
        res["rho_edge_excess"] = spearman(edge, ex)
        o = np.argsort(-edge)
        d10 = max(len(o) // 10, 1)
        res["top_decile_excess"] = round(float(ex[o[:d10]].mean()), 3)
        res["bottom_decile_excess"] = round(float(ex[o[-d10:]].mean()), 3)
        big = np.abs(py) > 0.25
        res["direction_hit"] = (
            round(float(((v[big] > 0) == (py[big] > 0)).mean()), 3) if big.any() else None
        )
        # m150cap3 book vs random baskets under the same constraints
        bk = sorted(
            (
                (vv - e, a, b, e, vv)
                for (a, b, e, _p), vv in ((u[:4], values.get(u[:2])) for u in univ)
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
            rng = random.Random(rng_seed)
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
        print("  " + json.dumps(res), flush=True)
        return res

    results = []
    for v, label in ((1, "V1 year-ago"), (2, "V2 + drift"), (3, "V3 + weather"), (4, "V4 actual")):
        hours, P = base_flows[v]
        L, S, mode = loading(hours, P)
        p95 = np.percentile(L, 95, axis=0)
        sgn = np.sign(np.median(S, axis=0) + 1e-9)
        order = [k for k in np.argsort(-p95) if idxs[k] not in hot_never][:TOPK]
        pred = [
            (idxs[k], sgn[k], bound_val.get(idxs[k], 0.5 * med), mode.get(idxs[k], -1))
            for k in order
        ]
        elems = [(row(n, ci), s, val) for n, s, val, ci in pred]
        results.append(evaluate(label, path_values(elems), p95, pred))
        if v == 4:
            v4_sign = {idxs[k]: sgn[k] for k in range(len(idxs))}
            v4_mode = mode
    # V5: the delivery month's actual binding constraints valued through the model
    elems = []
    cidx = {nm: k for k, nm in enumerate(n1.names)}
    for (name, cont), dollars in truth.items():
        brs = [n for n in truth_br[(name, cont)] if n in v4_sign or n in mon_br]
        if not brs:
            continue
        ci = cidx.get(cont, v4_mode.get(brs[0], -1)) if cont else -1
        for n in brs:
            elems.append(
                (row(n, ci if n in srow else None), v4_sign.get(n, 1.0), dollars / nh / len(brs))
            )
    results.append(evaluate("V5 actual constraints", path_values(elems)))
    outd = ARCHIVE / "out" / "experiment"
    outd.mkdir(parents=True, exist_ok=True)
    (outd / f"injection_{args.month}.json").write_text(
        json.dumps(
            dict(
                month=args.month,
                asof=str(asof),
                growth=growth,
                removed_units=len(n_removed),
                added_units=n_added,
                universe=len(univ),
                results=results,
            ),
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
