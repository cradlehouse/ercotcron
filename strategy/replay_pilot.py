#!/usr/bin/env python3
"""Grid replay pilot (A1 reconstruction, tuning window): does a DC power flow of
the day-ahead market's own injections, on that month's CRR network model, load
the constraints that actually bound in DAM, in the hours they bound?

    python strategy/replay_pilot.py --month 2025-10 --tou PeakWD [--top 60]

Injections per hour (60-Day DAM Disclosure tables): resource awards at their
settlement point; virtual offers (+) and bids (-); PTP awards (+source -sink).
Settlement point -> PSS/E buses via ERCOT's Settlement_Points file: resource
nodes to their buses, hubs equally over hub buses, load zones weighted by the
model's bus loads. Residual imbalance is spread over all load buses.
For each DAM-binding (element, contingency) in the month's TOU hours: the
element is resolved to model branches by its stations and kV; the contingency
by ERCOT's contingency file; post-contingency flow from a DC solve with those
branches removed; loading = |flow| / emergency rating (monitored-element file,
else RAW rate). Score: per-constraint AUC of loading for binding vs non-binding
hours, pooled AUC, and resolution coverage. Read-only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from scipy.sparse import csc_matrix, lil_matrix
from scipy.sparse.linalg import factorized

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pathlib

import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import REF, ROOT
from strategy.ptdf import parse_raw

load_dotenv(ROOT / ".env")
MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def raw_loads(path):
    lines = open(path, encoding="latin-1").read().split("\n")
    s = next(i for i, ln in enumerate(lines) if "END OF BUS DATA" in ln)
    e = next(i for i, ln in enumerate(lines) if "END OF LOAD DATA" in ln)
    pl = defaultdict(float)
    for ln in lines[s + 1:e]:
        p = [x.strip().strip("'") for x in re.sub(r"/\*.*?\*/", "", ln).split(",")]
        try:
            if p[2] == "1":
                pl[int(p[0])] += max(float(p[5]), 0.0)
        except (ValueError, IndexError):
            pass
    return pl


_GEN_CACHE: dict = {}


def raw_gen_buses(path):
    if path in _GEN_CACHE:
        return _GEN_CACHE[path]
    lines = open(path, encoding="latin-1").read().split("\n")
    s = next(i for i, ln in enumerate(lines) if "END OF LOAD DATA" in ln)
    e = next(i for i, ln in enumerate(lines) if "END OF GENERATOR DATA" in ln)
    out = set()
    for ln in lines[s + 1:e]:
        try:
            out.add(abs(int(ln.split(",")[0])))
        except ValueError:
            pass
    _GEN_CACHE[path] = out
    return out


class Grid:
    def __init__(self, raw):
        self.buses, br = parse_raw(pathlib.Path(raw))
        adj = defaultdict(set)
        for b in br:
            adj[b["i"]].add(b["j"]); adj[b["j"]].add(b["i"])
        swing = [b for b in sorted(self.buses) if self.buses[b]["type"] == 3 and b in adj]
        self.slack = swing[0] if swing else next(iter(adj))
        seen, st = set(), [self.slack]
        while st:
            x = st.pop()
            if x not in seen:
                seen.add(x); st.extend(adj[x] - seen)
        self.ids = sorted(seen)
        self.idx = {b: k for k, b in enumerate(self.ids)}
        self.br = [b for b in br if b["i"] in seen and b["j"] in seen]
        self.key = {}
        for n, b in enumerate(self.br):
            self.key.setdefault((min(b["i"], b["j"]), max(b["i"], b["j"]), str(b["ckt"]).strip()), []).append(n)
        self.cache = {}

    def solver(self, out=frozenset()):
        if out in self.cache:
            return self.cache[out]
        nb = len(self.ids)
        B = lil_matrix((nb, nb))
        for n, b in enumerate(self.br):
            if n in out:
                continue
            i, j, y = self.idx[b["i"]], self.idx[b["j"]], 1.0 / b["x"]
            B[i, i] += y; B[j, j] += y; B[i, j] -= y; B[j, i] -= y
        s = self.idx[self.slack]
        keep = np.array([k for k in range(nb) if k != s])
        try:
            f = factorized(csc_matrix(B[keep, :][:, keep]))
        except RuntimeError:
            f = None  # contingency islands the network
        self.cache[out] = (f, keep)
        return self.cache[out]

    def flows(self, P_mw, out, branches):
        f, keep = self.solver(out)
        if f is None:
            return None
        th = np.zeros(len(self.ids))
        th[keep] = f(P_mw[keep] / 100.0)
        return np.array([[100.0 * (th[self.idx[self.br[n]["i"]]] - th[self.idx[self.br[n]["j"]]]) / self.br[n]["x"]
                          for n in branches]])[0]


def auc(pos, neg):
    if not pos or not neg:
        return None
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    r, rank_sum = 1, 0.0
    i = 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        avg = (r + r + (j - i) - 1) / 2
        rank_sum += avg * sum(1 for k in range(i, j) if allv[k][1] == 1)
        r += j - i
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--tou", default="PeakWD")
    ap.add_argument("--top", type=int, default=60)
    args = ap.parse_args()
    y, m = map(int, args.month.split("-"))
    tag = f"{y}.{MON[m - 1]}.Monthly.Auction"
    M = REF / "crr_models"
    raw = next(M.glob(f"Common_{tag}_*_{args.tou}_Common_NetworkModel.RAW"))
    g = Grid(raw)
    pl = raw_loads(raw)
    print(f"model {raw.name}: {len(g.ids)} buses in main island, {len(g.br)} branches", flush=True)

    # settlement point -> {bus: weight}
    zf = zipfile.ZipFile(REF / "settlement_points_map.zip")
    spf = next(n for n in zf.namelist() if re.search(r"Settlement_Points_.*\.csv$", n))
    rn, hub, lz, sub_bus = defaultdict(set), defaultdict(set), defaultdict(set), defaultdict(set)
    for r in csv.DictReader(io.TextIOWrapper(zf.open(spf), encoding="latin-1")):
        try:
            b = int(r["PSSE_BUS_NUMBER"])
        except (TypeError, ValueError):
            continue
        if b not in g.idx:
            continue
        if r["RESOURCE_NODE"]:
            rn[r["RESOURCE_NODE"]].add(b)
        if r["HUB"]:
            hub[r["HUB"]].add(b)
        if r["SETTLEMENT_LOAD_ZONE"]:
            lz[r["SETTLEMENT_LOAD_ZONE"]].add(b)
        if r["SUBSTATION"]:
            sub_bus[r["SUBSTATION"]].add(b)
    # NOIE load zones (LZ_AEN, LZ_CPS, LZ_LCRA, LZ_RAYBN) come from their own file,
    # keyed by electrical bus
    eb_bus = {}
    for r in csv.DictReader(io.TextIOWrapper(zf.open(spf), encoding="latin-1")):
        try:
            eb_bus[r["ELECTRICAL_BUS"]] = int(r["PSSE_BUS_NUMBER"])
        except (TypeError, ValueError):
            pass
    nf = next((n for n in zf.namelist() if "NOIE_Mapping" in n), None)
    if nf:
        for r in csv.DictReader(io.TextIOWrapper(zf.open(nf), encoding="latin-1")):
            b = eb_bus.get(r["ELECTRICAL_BUS"])
            if b in g.idx and r["NOIE"]:
                lz[r["NOIE"]].add(b)
    gen_buses = {b for b in g.idx if b in raw_gen_buses(raw)}
    allhub = set().union(*hub.values()) if hub else set()
    load_w = {b: w for b, w in pl.items() if b in g.idx and w > 0}
    lw_tot = sum(load_w.values())

    def spread(sp):
        if sp in rn:
            bs = rn[sp]; return {b: 1 / len(bs) for b in bs}
        if sp in hub:
            bs = hub[sp]; return {b: 1 / len(bs) for b in bs}
        if sp in ("HB_HUBAVG", "HB_BUSAVG") and allhub:
            return {b: 1 / len(allhub) for b in allhub}
        if sp in lz:
            ws = {b: load_w.get(b, 0) for b in lz[sp]}
            t = sum(ws.values())
            if t > 0:
                return {b: w / t for b, w in ws.items() if w > 0}
            return {b: 1 / len(lz[sp]) for b in lz[sp]}
        # combined-cycle logical nodes and unit-level names (DDPEC_CC1, OGSES_1):
        # the prefix is the plant's substation; use its generator buses
        st = sp.split("_")[0]
        bs = {b for b in sub_bus.get(st, set()) if b in gen_buses} or sub_bus.get(st, set())
        if bs:
            return {b: 1 / len(bs) for b in bs}
        return None
    sp_cache, unmapped = {}, defaultdict(float)

    def add(P, sp, mw):
        if not mw:
            return
        if sp not in sp_cache:
            sp_cache[sp] = spread(sp)
        w = sp_cache[sp]
        if w is None:
            unmapped[sp] += abs(mw); return
        for b, f in w.items():
            P[g.idx[b]] += mw * f

    # hours of the month in this TOU
    d, days = date(y, m, 1), []
    while d.month == m:
        days.append(d); d += timedelta(days=1)
    hours = [(dd, he) for dd in days for he in range(1, 25) if tou_of(dd, he) == args.tou]
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        res = c.execute("select delivery_date, settlement_point, awarded_mw from dam_resource_awards where delivery_date between %s and %s",
                        (days[0], days[-1])).fetchall()
        vir = c.execute("select delivery_date, settlement_point, offer_mw, bid_mw from dam_virtual_awards where delivery_date between %s and %s",
                        (days[0], days[-1])).fetchall()
        ptp = c.execute("""select delivery_date, source, sink, mw from dam_ptp_awards where delivery_date between %s and %s""",
                        (days[0], days[-1])).fetchall()
        dc = c.execute("""select delivery_date, hour_ending, constraint_name, contingency, from_station, to_station, from_kv, shadow_price
                            from dam_constraints where delivery_date between %s and %s""", (days[0], days[-1])).fetchall()
    print(f"injection rows: {len(res)} resource-days, {len(vir)} virtual, {len(ptp)} PTP; DAM constraint-hours {len(dc)}", flush=True)
    nb = len(g.ids)
    P = {h: np.zeros(nb) for h in hours}
    hs = set(hours)
    for dd, sp, arr in res:
        for k, v in enumerate(arr):
            if (dd, k + 1) in hs and v:
                add(P[(dd, k + 1)], sp, v)
    for dd, sp, off, bid in vir:
        for k in range(len(off)):
            if (dd, k + 1) in hs:
                add(P[(dd, k + 1)], sp, (off[k] or 0) - (bid[k] or 0))
    for dd, so, si, arr in ptp:
        for k, v in enumerate(arr):
            if (dd, k + 1) in hs and v:
                add(P[(dd, k + 1)], so, v); add(P[(dd, k + 1)], si, -v)
    imb = []
    for h in hours:
        tot = P[h].sum()
        imb.append(tot)
        for b, w in load_w.items():
            P[h][g.idx[b]] -= tot * w / lw_tot
    print("largest unmapped settlement points (MW/h):", [(k, round(v / len(hours))) for k, v in sorted(unmapped.items(), key=lambda x: -x[1])[:15]])
    print(f"hourly residual imbalance spread over loads: median {np.median(imb):,.0f} MW; "
          f"unmapped settlement points {len(unmapped)} ({sum(unmapped.values()) / len(hours):,.0f} MW/h avg)", flush=True)

    # constraints binding in these hours
    bind = defaultdict(dict)
    meta = {}
    for dd, he, name, cont, fs, ts, kv, spv in dc:
        if (dd, he) in hs and spv and float(spv) > 0:
            k = (name, cont)
            bind[k][(dd, he)] = bind[k].get((dd, he), 0) + float(spv)
            meta[k] = (fs, ts, float(kv) if kv else None)
    top = sorted(bind, key=lambda k: -sum(bind[k].values()))[: args.top]
    # ratings + contingency definitions
    mon = {}
    for r in csv.DictReader(open(next(M.glob(f"Common_MonitoredLinesAndTransformers_{tag}_*.CSV")))):
        if r["TimeOfUse"] == args.tou:
            p = r["DeviceName"].split()
            try:
                mon[(min(int(p[0]), int(p[2])), max(int(p[0]), int(p[2])), p[4])] = float(r["EmergencyRating"])
            except (ValueError, IndexError):
                pass
    cdef = defaultdict(list)
    for r in csv.DictReader(open(next(M.glob(f"Common_Contingencies_{tag}_*.CSV")))):
        p = r["DeviceName"].split()
        try:
            cdef[r["Contingency"]].append((min(int(p[0]), int(p[2])), max(int(p[0]), int(p[2])), p[4]))
        except (ValueError, IndexError):
            pass

    def buses_of(station, kv):
        if not station:
            return set()
        bs = set(sub_bus.get(station, set()))
        bs |= {b for b, v in g.buses.items() if b in g.idx and v["name"].upper().startswith(station[:8].upper())}
        if kv and kv > 1:
            bs2 = {b for b in bs if abs(g.buses[b]["kv"] - kv) < 2}
            return bs2 or bs
        return bs

    results, unresolved = [], defaultdict(int)
    for k in top:
        name, cont = k
        fs, ts, kv = meta[k]
        A, Bset = buses_of(fs, kv), buses_of(ts or fs, kv)
        el = [n for n, b in enumerate(g.br) if (b["i"] in A and b["j"] in Bset) or (b["j"] in A and b["i"] in Bset)]
        if fs == ts:
            el = [n for n in el if g.br[n]["kind"] == "xfmr"] or el
        if not el:
            unresolved["element"] += 1; continue
        out = set()
        if cont and cont.upper() not in ("BASE CASE", "BASECASE"):
            if cont not in cdef:
                unresolved["contingency"] += 1; continue
            for key in cdef[cont]:
                out |= set(g.key.get(key, []))
        out -= set(el)
        loads = {}
        for h in hours:
            fl = g.flows(P[h], frozenset(out), el)
            if fl is None:
                break
            best = 0.0
            for n, f in zip(el, fl, strict=True):
                b = g.br[n]
                kk = (min(b["i"], b["j"]), max(b["i"], b["j"]), str(b["ckt"]).strip())
                rate = mon.get(kk) or b["rate"] or None
                if rate:
                    best = max(best, abs(f) / rate)
            loads[h] = best
        if not loads:
            unresolved["islanding"] += 1; continue
        pos = [loads[h] for h in hours if h in bind[k]]
        neg = [loads[h] for h in hours if h not in bind[k]]
        results.append(dict(constraint=name, contingency=cont, dollars=round(sum(bind[k].values())), bind_hours=len(pos),
                            auc=auc(pos, neg), load_bind=float(np.median(pos)) if pos else None,
                            load_other=float(np.median(neg)) if neg else None))
    good = [r for r in results if r["auc"] is not None]
    print(f"\nconstraints evaluated {len(results)} of top {len(top)}; unresolved: {dict(unresolved)}")
    if good:
        aucs = sorted(r["auc"] for r in good)
        w = sum(r["auc"] * r["dollars"] for r in good) / sum(r["dollars"] for r in good)
        print(f"AUC (loading separates binding from non-binding hours; 0.5 = no skill): median {aucs[len(aucs)//2]:.2f}, "
              f"$-weighted {w:.2f}, share > 0.6: {100*sum(a > 0.6 for a in aucs)/len(aucs):.0f}%")
    for r in sorted(results, key=lambda r: -r["dollars"])[:20]:
        a = "  -  " if r["auc"] is None else f"{r['auc']:.2f}"
        print(f"  {r['constraint'][:18]:18} {str(r['contingency'])[:10]:10} ${r['dollars']:>8,} bind {r['bind_hours']:3}h  "
              f"AUC {a}  loading binding {r['load_bind'] or 0:5.2f} vs other {r['load_other'] or 0:5.2f}")
    out = REF / f"replay_pilot_{args.month}_{args.tou}.json"
    json.dump(dict(model=raw.name, hours=len(hours), results=results, unresolved=dict(unresolved)), open(out, "w"), indent=1, default=str)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
