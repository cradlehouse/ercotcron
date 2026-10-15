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
import difflib
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
        self.buses, br = parse_raw(pathlib.Path(raw), zero_x=1e-4)
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
        """Factorised B for the slack's component with `out` branches removed.
        A contingency that islands part of the grid keeps the main component;
        injections on the islanded buses are dropped (reported as islanded)."""
        if out in self.cache:
            return self.cache[out]
        adj = defaultdict(list)
        for n, b in enumerate(self.br):
            if n not in out:
                adj[b["i"]].append(b["j"]); adj[b["j"]].append(b["i"])
        comp, st = set(), [self.slack]
        while st:
            x = st.pop()
            if x not in comp:
                comp.add(x); st.extend(adj[x])
        cid = sorted(comp)
        cix = {b: k for k, b in enumerate(cid)}
        nb = len(cid)
        B = lil_matrix((nb, nb))
        for n, b in enumerate(self.br):
            if n in out or b["i"] not in cix or b["j"] not in cix:
                continue
            i, j, y = cix[b["i"]], cix[b["j"]], 1.0 / b["x"]
            B[i, i] += y; B[j, j] += y; B[i, j] -= y; B[j, i] -= y
        s0 = cix[self.slack]
        keep = [k for k in range(nb) if k != s0]
        try:
            f = factorized(csc_matrix(B[keep, :][:, keep]))
        except RuntimeError:
            f = None
        gkeep = np.array([self.idx[cid[k]] for k in keep])
        self.cache[out] = (f, gkeep, cix, len(self.ids) - nb)
        return self.cache[out]

    def flows(self, P_mw, out, branches):
        f, gkeep, cix, _islanded = self.solver(out)
        if f is None:
            return None
        th = np.zeros(len(self.ids))
        th[gkeep] = f(P_mw[gkeep] / 100.0)
        res = []
        for n in branches:
            b = self.br[n]
            if b["i"] in cix and b["j"] in cix:
                res.append(100.0 * (th[self.idx[b["i"]]] - th[self.idx[b["j"]]]) / b["x"])
            else:
                res.append(0.0)
        return np.array(res)


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
    ap.add_argument("--precision", action="store_true",
                    help="also score every monitored element: do the ones that bound stand out from the ones that never did?")
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
    # Join on the PSS/E bus NAME first: the mapping file postdates older models
    # and ~3% of its bus numbers point at a different bus there than its names do.
    byname = {v["name"].upper(): b for b, v in g.buses.items() if b in g.idx}
    for r in csv.DictReader(io.TextIOWrapper(zf.open(spf), encoding="latin-1")):
        b = byname.get((r["PSSE_BUS_NAME"] or "").strip().upper())
        if b is None:
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
        b = byname.get((r["PSSE_BUS_NAME"] or "").strip().upper())
        if b is None:
            try:
                b = int(r["PSSE_BUS_NUMBER"])
            except (TypeError, ValueError):
                continue
        eb_bus[r["ELECTRICAL_BUS"]] = b
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
        if not bs and len(st) >= 3:
            # mapping-file bus numbers can postdate the model: fall back to the
            # model's own generator buses whose name starts with the station code
            bs = {b for b in gen_buses if g.buses[b]["name"].upper().startswith(st.upper())}
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
        # zonal load forecast as known when DAM cleared: the 09:30 edition of the day before
        fz = defaultdict(dict)  # day -> zone -> [24]
        for dd, zone, vals in c.execute("""
              select v.delivery_date, v.series, v.vals from ercot_forecast_vintages v
               where v.product = 'NP3-560-CD' and v.delivery_date between %s and %s
                 and v.series in ('Houston','North','South','West')
                 and v.posted_at = (select max(w.posted_at) from ercot_forecast_vintages w
                                     where w.product = 'NP3-560-CD' and w.delivery_date = v.delivery_date
                                       and w.posted_at < v.delivery_date - interval '14 hours')""", (days[0], days[-1])):
            fz[dd][zone] = vals
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
    # Residual withdrawals (load not itemised in the disclosure) go to the four
    # forecast zones in proportion to ERCOT's decision-time zonal forecast, then
    # to buses within a zone by the model's bus loads. Days without a forecast
    # edition fall back to the model's static load pattern.
    ZONE = {"LZ_HOUSTON": "Houston", "LZ_NORTH": "North", "LZ_RAYBN": "North", "LZ_SOUTH": "South",
            "LZ_AEN": "South", "LZ_CPS": "South", "LZ_LCRA": "South", "LZ_WEST": "West"}
    bus_zone = {}
    for zname, bs in lz.items():
        for b in bs:
            if ZONE.get(zname):
                bus_zone.setdefault(b, ZONE[zname])
    zw = defaultdict(dict)
    for b, w in load_w.items():
        zw[bus_zone.get(b, "_none")][b] = w
    zt = {z: sum(v.values()) for z, v in zw.items()}
    imb, zonal_days = [], 0
    for h in hours:
        tot = P[h].sum()
        imb.append(tot)
        f = fz.get(h[0], {})
        if len(f) == 4 and all(f[z] and len(f[z]) >= h[1] and f[z][h[1] - 1] for z in f):
            fv = {z: f[z][h[1] - 1] for z in f}
            ft = sum(fv.values())
            for z, share in ((z, fv[z] / ft) for z in fv):
                for b, w in zw.get(z, {}).items():
                    P[h][g.idx[b]] -= tot * share * w / zt[z]
            zonal_days += 1
        else:
            for b, w in load_w.items():
                P[h][g.idx[b]] -= tot * w / lw_tot
    print(f"zonal load allocation used for {zonal_days} of {len(hours)} hours", flush=True)
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
    def read_cont(path):
        out = defaultdict(list)
        for r in csv.DictReader(open(path)):
            p = r["DeviceName"].split()
            try:
                out[r["Contingency"]].append((min(int(p[0]), int(p[2])), max(int(p[0]), int(p[2])), p[4]))
            except (ValueError, IndexError):
                pass
        return out
    own = next(M.glob(f"Common_Contingencies_{tag}_*.CSV"))
    cdef = read_cont(own)
    for other in sorted(M.glob("Common_Contingencies_*.CSV")):
        if other != own:
            for k, v in read_cont(other).items():
                cdef.setdefault(k, v)  # contingency missing this month: borrow its definition
    # interfaces (generic transmission limits): this month's non-thermal file, then others
    iface = {}
    for path in [next(M.glob(f"Common_Non_ThermalConstraints_{tag}_*.CSV"), None), *sorted(M.glob("Common_Non_ThermalConstraints_*.CSV"))]:
        if not path:
            continue
        rows = defaultdict(list)
        for r in csv.DictReader(open(path), skipinitialspace=True):
            p = r["DeviceName"].split()
            try:
                rows[r["Name"]].append((int(p[0]), int(p[2]), p[4], 1 if r["FlowDirection"].strip() == "From-To" else -1,
                                        float(r["Factor"]), float(r["Limit"])))
            except (ValueError, IndexError, KeyError):
                pass
        for k, v in rows.items():
            iface.setdefault(k, v)

    def buses_of(station, kv):
        if not station:
            return set()
        bs = set(sub_bus.get(station, set()))
        bs |= {b for b, v in g.buses.items() if b in g.idx and v["name"].upper().startswith(station[:8].upper())}
        if kv and kv > 1:
            bs2 = {b for b in bs if abs(g.buses[b]["kv"] - kv) < 2}
            return bs2 or bs
        return bs

    adjk = defaultdict(list)  # bus -> [(neighbour, branch index)]
    for n, b in enumerate(g.br):
        adjk[b["i"]].append((b["j"], n)); adjk[b["j"]].append((b["i"], n))

    def same_kv(b, kv):
        return not kv or kv <= 1 or abs(g.buses[b]["kv"] - kv) < 2

    def resolve_element(fs, ts, kv):
        A = buses_of(fs, kv)
        if not ts or ts == fs:
            # in-station transformer: one side at kV, the other at any voltage
            allb = buses_of(fs, None)
            el = [n for n, b in enumerate(g.br) if b["kind"] == "xfmr"
                  and ((b["i"] in A and b["j"] in allb) or (b["j"] in A and b["i"] in allb))]
            return el
        Bset = buses_of(ts, kv)
        el = [n for n, b in enumerate(g.br) if (b["i"] in A and b["j"] in Bset) or (b["j"] in A and b["i"] in Bset)]
        if el:
            return el
        if A and not Bset:
            # far end is a tap missing from the mapping: nearest same-kV neighbour
            # (<= 2 hops) whose name best matches the station code
            near = {}
            for a in A:
                for nb1, _ in adjk[a]:
                    if same_kv(nb1, kv):
                        near.setdefault(nb1, 1)
                        for nb2, _ in adjk[nb1]:
                            if same_kv(nb2, kv) and nb2 not in A:
                                near.setdefault(nb2, 2)
            sc = [(difflib.SequenceMatcher(None, ts.upper(), g.buses[b]["name"].upper()[:len(ts) + 2]).ratio(), b) for b in near]
            sc = [x for x in sc if x[0] >= 0.5]
            if sc:
                Bset = {max(sc)[1]}
        if not A and Bset:
            return resolve_element(ts, fs, kv)
        if A and Bset:
            # series line through unmapped tap buses: shortest same-kV path (<= 3
            # hops); the constraint's flow is the segment leaving the from-station
            frontier, prev = list(A), {a: None for a in A}
            for _ in range(3):
                nxt = []
                for x in frontier:
                    for y, n in adjk[x]:
                        if y not in prev and same_kv(y, kv):
                            prev[y] = (x, n)
                            if y in Bset:
                                path, cur = [], y
                                while prev[cur]:
                                    path.append(prev[cur][1]); cur = prev[cur][0]
                                return [path[-1]]
                            nxt.append(y)
                frontier = nxt
        return []

    results, unresolved, why = [], defaultdict(int), []
    for k in top:
        name, cont = k
        fs, ts, kv = meta[k]
        signs = None
        if name in iface and (not fs or (fs == ts and not buses_of(fs, kv))):
            # interface: signed, factored sum of its lines' flows against its limit
            el, signs, limit = [], [], iface[name][0][5]
            for fi, ti, ck, sg, fac, _lim in iface[name]:
                for n in g.key.get((min(fi, ti), max(fi, ti), ck), []):
                    el.append(n); signs.append(sg * fac * (1 if g.br[n]["i"] == fi else -1))
        else:
            el = resolve_element(fs, ts, kv)
        if not el:
            unresolved["element"] += 1
            why.append(dict(constraint=name, contingency=cont, reason="element", fs=fs, ts=ts, kv=kv,
                            buses_from=len(buses_of(fs, kv)), buses_to=len(buses_of(ts, kv)), dollars=round(sum(bind[k].values()))))
            continue
        out = set()
        if cont and cont.upper() not in ("BASE CASE", "BASECASE"):
            if cont not in cdef:
                unresolved["contingency"] += 1
                why.append(dict(constraint=name, contingency=cont, reason="contingency", dollars=round(sum(bind[k].values()))))
                continue
            for key in cdef[cont]:
                out |= set(g.key.get(key, []))
        out -= set(el)
        loads = {}
        for h in hours:
            fl = g.flows(P[h], frozenset(out), el)
            if fl is None:
                break
            if signs is not None:
                loads[h] = abs(sum(sg * f for sg, f in zip(signs, fl, strict=True))) / limit
                continue
            best = 0.0
            for n, f in zip(el, fl, strict=True):
                b = g.br[n]
                kk = (min(b["i"], b["j"]), max(b["i"], b["j"]), str(b["ckt"]).strip())
                rate = mon.get(kk) or b["rate"] or None
                if rate:
                    best = max(best, abs(f) / rate)
            loads[h] = best
        if not loads:
            unresolved["islanding"] += 1
            why.append(dict(constraint=name, contingency=cont, reason="islanding", n_out=len(out), dollars=round(sum(bind[k].values()))))
            continue
        pos = [loads[h] for h in hours if h in bind[k]]
        neg = [loads[h] for h in hours if h not in bind[k]]
        results.append(dict(constraint=name, contingency=cont, dollars=round(sum(bind[k].values())), bind_hours=len(pos),
                            auc=auc(pos, neg), load_bind=float(np.median(pos)) if pos else None,
                            load_other=float(np.median(neg)) if neg else None))
    if args.precision:
        # Spatial precision (plan addendum: hit rate alone rewards predicting
        # tight everywhere). Positives: model branches of EVERY constraint that
        # bound in these hours (resolved as above). Negatives: every other
        # monitored element. Score each element by its 95th-percentile
        # base-case loading over the month's hours.
        pos_br = set()
        for k in bind:
            fs, ts, kv = meta[k]
            pos_br |= set(resolve_element(fs, ts, kv)) if fs else set()
        mon_br = {}
        for key, rate in mon.items():
            for n in g.key.get(key, []):
                if rate:
                    mon_br[n] = rate
        idxs = sorted(mon_br)
        load = np.zeros((len(hours), len(idxs)))
        for t, h in enumerate(hours):
            load[t] = np.abs(g.flows(P[h], frozenset(), idxs)) / np.array([mon_br[n] for n in idxs])
        p95 = np.percentile(load, 95, axis=0)
        lab = [n in pos_br for n in idxs]
        pv = [v for v, lb in zip(p95, lab, strict=True) if lb]
        nv = [v for v, lb in zip(p95, lab, strict=True) if not lb]
        order = np.argsort(-p95)
        prec = {kk: sum(lab[i] for i in order[:kk]) / kk for kk in (25, 50, 100)}
        base = len(pv) / len(lab)
        print(f"\nPRECISION: monitored elements {len(idxs)}, of which bound this month {len(pv)} (base rate {100*base:.1f}%)")
        print(f"  AUC of p95 base-case loading, bound vs never-bound: {auc(list(pv), list(nv)):.2f}")
        print("  share that bound among the most-loaded elements: " +
              ", ".join(f"top {kk}: {100*v:.0f}% ({v/base:.1f}x base)" for kk, v in prec.items()))
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
    json.dump(dict(model=raw.name, hours=len(hours), results=results, unresolved=dict(unresolved), unresolved_detail=why), open(out, "w"), indent=1, default=str)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
