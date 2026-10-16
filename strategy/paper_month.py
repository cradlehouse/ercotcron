#!/usr/bin/env python3
"""Walk-forward paper bid for ONE monthly auction, built only from data known
at the auction cutoff (replay-plan addendum, 15 Oct 2026).

    python strategy/paper_month.py --delivery 2026-02 --asof 2026-01-11 [--tou PeakWD] [--freeze]

From MAY 2026 (plan addendum, after MAR): no DC ties / Laredo VFT, candidates
priced >= $0.25 only, books ranked by $ edge with at most 2 paths per source and
per sink, and the main signals are auction-anchored - value = latest clearing x
R (what paths paid / their clearing over recent completed months), tilted by
physics (1 + k x z). The signal list below predates that change; the code and
the addendum are authoritative.

Every run builds a slate of books from the same candidates and clearing
estimates, so one month tests many ideas at once (signal x bid rule):

Signals (expected $/MWh for each path):
  phys_base    analog month (same month last year, 60-Day DAM Disclosure, all
               dated <= asof-60); units on planned outages known by asof are
               replaced by gas pro rata system-wide; DC flows on the delivery
               month's CRR model. Each element's loading is the worst of the
               base case (vs base rating) and every contingency in the month's
               list (vs emergency rating), screened by distribution factors for
               the elements with p95 base loading >= 0.4 or binding history.
               Top-K elements by 95th-percentile loading after the hot-never
               filter; each worth its average peak DAM shadow over the 100 days
               to asof (else half the median); path value = sum of value x
               shift factor (after the element's usual worst contingency) x
               direction.
  phys_n0      the same without contingencies (base case only).
  phys_local   outaged units replaced by gas in their own load zone first.
  phys_lull / phys_windy / phys_cold
               the same with a weather stress on the analog: -4 GW wind,
               +6 GW wind, or -2 GW wind with load +15%; wind moved at the
               farms by offered capability, gas fills the gap. Each element's
               $ is scaled by (scenario / base mean loading)^2, 0.25x..4x.
  phys_robust  the lowest of base/lull/windy/cold (pays in any weather).
  phys_wxavg   the average of those four.
  phys_nofilter  phys_base without the hot-never filter.
  phys_recent  injections from the latest 30 disclosed days, not last year.
  hist100 / hist30  the path's realized average peak DAM spread over the
               100 / 30 days to asof (history only, no physics).
  consensus    the lower of phys_base and hist100 (both must agree).
Bid rules: buy where value >= ratio x expected clearing (floor 5c), limit =
  value / ratio, 5 MW each; m125 / m150 / m200 keep the top 60 by
  value/clearing; wide110 bids down to 1.1x and keeps up to 150.
random__control: 60 candidates drawn with a seed from the month, bid at 1.5x
  expected clearing - what luck alone scores.
Candidates are every peak OBL path awarded in the two prior monthly auctions;
expected clearing = the latest auction's nodal clearing (source - sink); no
counterflow.
--freeze writes every book + a manifest under ARCHIVE/out/sealed/paper_<month>_<tou>/
and prints SHA-256s; it refuses to overwrite. Scoring is a separate step.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of
from strategy.common import ARCHIVE, REF, ROOT
from strategy.replay_pilot import Grid, raw_gen_buses, raw_loads

load_dotenv(ROOT / ".env")
MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
TOPK, MAX_BIDS, MW, HOT = 100, 60, 5, 0.8
# after MAR 2026 (see the plan's addendum): no DC ties / Laredo VFT, no paths
# priced under 25c, at most 2 per source and per sink, rank by $ edge
MIN_CLEAR, NODE_CAP = 0.25, 2
TILTS = (0.25, 0.5, 1.0)
ANCHOR_PHYS = (
    "phys_base",
    "phys_n0",
    "phys_lull",
    "phys_windy",
    "phys_cold",
    "phys_recent",
    "phys_nofilter",
    "phys_local",
    "phys_grow",
)
ANCHORED = ("phys_base", "phys_n0", "phys_windy", "phys_robust", "phys_recent", "phys_grow")


def excluded(sp):
    """DC ties and the Laredo VFT: flows set by operators, not by the network."""
    return sp.startswith("DC_") or sp.startswith("LARDVFT")


# bid rules: name -> (required value / clearing, max bids); limit = value / ratio
RULES = {
    "m125": (1.25, MAX_BIDS, None),
    "m150": (1.5, MAX_BIDS, None),
    "m200": (2.0, MAX_BIDS, None),
    "wide110": (1.10, 150, None),
    # from JUL: the same, only paths expected to clear at <= $3
    "m125cap3": (1.25, MAX_BIDS, 3.0),
    "m150cap3": (1.5, MAX_BIDS, 3.0),
}
WEATHER = ("base", "lull", "windy", "cold")
# after JUL (plan addendum): the $3 cap and counterflow are the default; a smaller slate
FOCUS_SIGNALS = (
    "phys_base",
    "phys_windy",
    "phys_recent",
    "anch25_base",
    "hist100",
    "market",
    "market_veto",
)
FOCUS_RULES = ("m125cap3", "m150cap3")
FOCUS_CONTROLS = ("random__control", "vetorand__control", "cf_phys__keep75", "cf_random__keep75")
VETO_Q = 0.2  # physics veto: drop the candidates in the bottom 20% of physics edge
CF_BAND, CF_KEEP = (-3.0, -0.25), 0.75
ZONE = {
    "LZ_HOUSTON": "Houston",
    "LZ_NORTH": "North",
    "LZ_RAYBN": "North",
    "LZ_SOUTH": "South",
    "LZ_AEN": "South",
    "LZ_CPS": "South",
    "LZ_LCRA": "South",
    "LZ_WEST": "West",
}


def month_days(y, m):
    d, out = date(y, m, 1), []
    while d.month == m:
        out.append(d)
        d += timedelta(days=1)
    return out


class Mapper:
    """Settlement point -> {bus: weight} on one grid (name-first join)."""

    def __init__(self, g, raw):
        self.g = g
        zf = zipfile.ZipFile(REF / "settlement_points_map.zip")
        spf = next(n for n in zf.namelist() if re.search(r"Settlement_Points_.*\.csv$", n))
        byname = {v["name"].upper(): b for b, v in g.buses.items() if b in g.idx}
        self.rn, self.hub, self.lz, self.sub = (defaultdict(set) for _ in range(4))
        eb = {}
        for r in csv.DictReader(io.TextIOWrapper(zf.open(spf), encoding="latin-1")):
            b = byname.get((r["PSSE_BUS_NAME"] or "").strip().upper())
            if b is None:
                try:
                    b = int(r["PSSE_BUS_NUMBER"])
                except (TypeError, ValueError):
                    continue
            if b not in g.idx:
                continue
            eb[r["ELECTRICAL_BUS"]] = b
            if r["RESOURCE_NODE"]:
                self.rn[r["RESOURCE_NODE"]].add(b)
            if r["HUB"]:
                self.hub[r["HUB"]].add(b)
            if r["SETTLEMENT_LOAD_ZONE"]:
                self.lz[r["SETTLEMENT_LOAD_ZONE"]].add(b)
            if r["SUBSTATION"]:
                self.sub[r["SUBSTATION"]].add(b)
        nf = next((n for n in zf.namelist() if "NOIE_Mapping" in n), None)
        if nf:
            for r in csv.DictReader(io.TextIOWrapper(zf.open(nf), encoding="latin-1")):
                b = eb.get(r["ELECTRICAL_BUS"])
                if b in g.idx and r["NOIE"]:
                    self.lz[r["NOIE"]].add(b)
        self.gen = {b for b in g.idx if b in raw_gen_buses(raw)}
        self.load_w = {b: w for b, w in raw_loads(raw).items() if b in g.idx and w > 0}
        self.allhub = set().union(*self.hub.values()) if self.hub else set()
        self.cache = {}

    def spread(self, sp):
        if sp in self.cache:
            return self.cache[sp]
        w = None
        if sp in self.rn:
            w = {b: 1 / len(self.rn[sp]) for b in self.rn[sp]}
        elif sp in self.hub:
            w = {b: 1 / len(self.hub[sp]) for b in self.hub[sp]}
        elif sp in ("HB_HUBAVG", "HB_BUSAVG") and self.allhub:
            w = {b: 1 / len(self.allhub) for b in self.allhub}
        elif sp in self.lz:
            ws = {b: self.load_w.get(b, 0) for b in self.lz[sp]}
            t = sum(ws.values())
            w = (
                {b: v / t for b, v in ws.items() if v > 0}
                if t > 0
                else {b: 1 / len(self.lz[sp]) for b in self.lz[sp]}
            )
        else:
            st = sp.split("_")[0]
            bs = {b for b in self.sub.get(st, set()) if b in self.gen} or self.sub.get(st, set())
            if not bs and len(st) >= 3:
                bs = {b for b in self.gen if self.g.buses[b]["name"].upper().startswith(st.upper())}
            if bs:
                w = {b: 1 / len(bs) for b in bs}
        self.cache[sp] = w
        return w


GAS = ("CCGT90", "CCLE90", "SCGT90", "SCLE90", "GSREH", "GSNONR", "GSSUP")
# weather stress scenarios on the analog month: (MW of wind added at wind farm
# locations, extra load share). DAM clears little wind (most sells in real
# time), so wind is moved by MW spread over the farms' offered capability
# (HSL), not by scaling awards. Gas absorbs the difference; residual load keeps
# the zonal forecast shape.
SCEN = {"base": (0.0, 0.0), "lull": (-4000.0, 0.0), "windy": (6000.0, 0.0), "cold": (-2000.0, 0.15)}


def injections(c, g, mp, days, tou, drop_resources=None, asof=None):
    """{(day, he): (other, wind, gas, load_shape)} from the DAM disclosure; the
    load shape (sums to 1) splits residual load by that day's zonal forecast."""
    if asof and max(days) > asof - timedelta(days=60):
        raise SystemExit(f"injections for {max(days)} were not public by {asof}")
    hours = [(d, he) for d in days for he in range(1, 25) if tou_of(d, he) == tou]
    hs, nb = set(hours), len(g.ids)
    # parts per hour: other, wind capability, gas, units on planned outage
    P = {h: (np.zeros(nb), np.zeros(nb), np.zeros(nb), np.zeros(nb)) for h in hours}
    drop = drop_resources or {}

    def add(vec, sp, mw):
        w = mp.spread(sp)
        if w and mw:
            for b, f in w.items():
                vec[g.idx[b]] += mw * f

    for d, res, rt, sp, arr, hsl in c.execute(
        """select delivery_date, resource, resource_type, settlement_point, awarded_mw, hsl_mw
            from dam_resource_awards where delivery_date between %s and %s""",
        (min(days), max(days)),
    ):
        out_ = res in drop.get(d, ())
        for k, v in enumerate(arr):
            if (d, k + 1) in hs and v:
                add(P[(d, k + 1)][3 if out_ else 2 if rt in GAS else 0], sp, v)
        if rt == "WIND" and hsl and not out_:
            for k, v in enumerate(hsl):
                if (d, k + 1) in hs and v:
                    add(P[(d, k + 1)][1], sp, v)
    for d, sp, off, bid in c.execute(
        "select delivery_date, settlement_point, offer_mw, bid_mw from dam_virtual_awards where delivery_date between %s and %s",
        (min(days), max(days)),
    ):
        for k in range(len(off)):
            if (d, k + 1) in hs:
                add(P[(d, k + 1)][0], sp, (off[k] or 0) - (bid[k] or 0))
    for d, so, si, arr in c.execute(
        "select delivery_date, source, sink, mw from dam_ptp_awards where delivery_date between %s and %s",
        (min(days), max(days)),
    ):
        for k, v in enumerate(arr):
            if (d, k + 1) in hs and v:
                add(P[(d, k + 1)][0], so, v)
                add(P[(d, k + 1)][0], si, -v)
    fz = defaultdict(dict)
    for d, zone, vals in c.execute(
        """select v.delivery_date, v.series, v.vals from ercot_forecast_vintages v
            where v.product='NP3-560-CD' and v.delivery_date between %s and %s and v.series in ('Houston','North','South','West')
              and v.posted_at = (select max(w.posted_at) from ercot_forecast_vintages w where w.product='NP3-560-CD'
                                 and w.delivery_date=v.delivery_date and w.posted_at < v.delivery_date - interval '14 hours')""",
        (min(days), max(days)),
    ):
        fz[d][zone] = vals
    bus_zone = {}
    for zn, bs in mp.lz.items():
        for b in bs:
            if ZONE.get(zn):
                bus_zone.setdefault(b, ZONE[zn])
    zw = defaultdict(dict)
    for b, w in mp.load_w.items():
        zw[bus_zone.get(b, "_none")][b] = w
    zt = {z: sum(v.values()) for z, v in zw.items()}
    lt = sum(mp.load_w.values())
    flat = np.zeros(nb)
    for b, w in mp.load_w.items():
        flat[g.idx[b]] = w / lt
    out = {}
    for h in hours:
        f = fz.get(h[0], {})
        if len(f) == 4 and all(f[z] and len(f[z]) >= h[1] and f[z][h[1] - 1] for z in f):
            ft = sum(f[z][h[1] - 1] for z in f)
            shape = np.zeros(nb)
            for z in f:
                for b, w in zw.get(z, {}).items():
                    shape[g.idx[b]] += f[z][h[1] - 1] / ft * w / zt[z]
        else:
            shape = flat
        out[h] = (*P[h], shape)
    return hours, out


def compose(parts, scen, zones=None):
    """Net injection vector for one hour under a weather scenario. Units on a
    planned outage are replaced by gas: pro rata system-wide, or (zones = list
    of bus masks) by gas in the same load zone first."""
    other, wcap, gas, dropped, shape = parts
    dw, xl = SCEN[scen]
    D = dropped.sum()
    if D > 0 and gas.sum() > 0:
        gas = gas.copy()
        left = D
        if zones is not None:
            for z in zones:
                gz, dz = gas[z].sum(), dropped[z].sum()
                if gz > 0 and dz > 0:
                    gas[z] *= 1 + dz / gz
                    left -= dz
        gas *= 1 + left / gas.sum()
    Wc, G = wcap.sum(), gas.sum()
    inj = other + gas
    if Wc > 0 and dw:
        inj = inj + dw * wcap / Wc
    if G > 0 and (dw or xl):
        need = G - dw + xl * (other.sum() + G)
        inj = inj + (max(need, 0.2 * G) / G - 1) * gas
    return inj - inj.sum() * shape


def device_branches(g, name, pairs):
    """ERCOT device name -> model branch indices. Lines read 'busA NAMEA busB
    NAMEB ckt'; transformers carry voltages in between ('busA NAMEA 345 busB
    NAMEB [kV] ckt id'), so the far bus is the first later number that forms a
    real branch with busA, and the circuit is the trailing token that matches."""
    p = name.split()
    try:
        i = int(p[0])
    except (ValueError, IndexError):
        return []
    for k in range(2, len(p)):
        if not p[k].isdigit():
            continue
        cand = pairs.get((min(i, int(p[k])), max(i, int(p[k]))))
        if not cand:
            continue
        if len(cand) == 1:
            return [cand[0][1]]
        for t in reversed(p[k + 2 :]):
            hit = [n for ckt, n in cand if str(ckt).strip() == t]
            if hit:
                return hit
        return [cand[0][1]]
    return []


class N1:
    """Post-contingency (N-1) screening on one CRR model by distribution
    factors: for contingency c removing branches K, the flow on screened
    element m becomes f_m + D_mK (I - D_KK)^-1 f_K, D = flow per 1 MW moved
    across each removed branch. Exact for DC flow, multi-element included;
    contingencies that island part of the grid are skipped."""

    def __init__(self, g, screen, conts):
        f, gkeep, _cix, _ = g.solver(frozenset())
        nb = len(g.ids)
        self.g, self.f, self.gkeep = g, f, gkeep
        self.I = np.array([g.idx[b["i"]] for b in g.br])
        self.J = np.array([g.idx[b["j"]] for b in g.br])
        self.X = np.array([b["x"] for b in g.br])
        self.screen = np.array(screen)
        srow = {n: r for r, n in enumerate(screen)}
        Ws, cols, starts, self.names, self.members = [], [], [], [], []
        mr, mc = [], []
        self.skipped = 0
        self.partial = 0
        for name, Kset in sorted(conts.items()):
            K = sorted(Kset)
            if not K:
                continue
            ths = []
            for n in K:
                rhs = np.zeros(nb)
                rhs[self.I[n]] += 1.0
                rhs[self.J[n]] -= 1.0
                th = np.zeros(nb)
                th[gkeep] = f(rhs[gkeep])
                ths.append(th)
            T = np.stack(ths, axis=1)
            Kx = np.array(K)
            DK = (T[self.I[Kx]] - T[self.J[Kx]]) / self.X[Kx][:, None]
            # removing all of K would cut off part of the grid (usually tap
            # stations of a tripped line): take elements out one at a time and
            # leave in service any that would complete the cut - it then carries
            # only the cut-off piece's own small injection
            keep = []
            for k in range(len(K)):
                t = [*keep, k]
                if np.linalg.svd(np.eye(len(t)) - DK[np.ix_(t, t)], compute_uv=False).min() > 1e-6:
                    keep = t
            if not keep:
                self.skipped += 1
                continue
            if len(keep) < len(K):
                self.partial += 1
                K, T = [K[k] for k in keep], T[:, keep]
                DK = DK[np.ix_(keep, keep)]
            A = np.eye(len(K)) - DK
            DM = (T[self.I[self.screen]] - T[self.J[self.screen]]) / self.X[self.screen][:, None]
            ci = len(self.names)
            starts.append(sum(len(k) for k in self.members))
            Ws.append((DM @ np.linalg.inv(A)).astype(np.float32))
            cols.extend(K)
            self.names.append(name)
            self.members.append(K)
            for n in K:
                if n in srow:
                    mr.append(srow[n])
                    mc.append(ci)
        self.W = np.hstack(Ws)
        self.cols = np.array(cols)
        self.starts = np.array(starts)
        self.mask = (np.array(mr, dtype=int), np.array(mc, dtype=int))

    def flows(self, P_mw):
        th = np.zeros(len(self.g.ids))
        th[self.gkeep] = self.f(P_mw[self.gkeep] / 100.0)
        return 100.0 * (th[self.I] - th[self.J]) / self.X

    def post(self, fl):
        """screened elements x contingencies post-contingency flows."""
        d = self.W * fl[self.cols].astype(np.float32)[None, :]
        out = fl[self.screen].astype(np.float32)[:, None] + np.add.reduceat(d, self.starts, axis=1)
        out[self.mask] = 0.0
        return out


def ptdf_row(g, n):
    """Flow on branch n per 1 MW injected at each bus (withdrawn at slack)."""
    f, gkeep, _cix, _ = g.solver(frozenset())
    b = g.br[n]
    rhs = np.zeros(len(g.ids))
    rhs[g.idx[b["i"]]] += 1.0
    rhs[g.idx[b["j"]]] -= 1.0
    th = np.zeros(len(g.ids))
    th[gkeep] = f(rhs[gkeep])
    return th / b["x"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery", required=True)
    ap.add_argument("--asof", required=True)
    ap.add_argument("--tou", default="PeakWD")
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument(
        "--focused",
        action="store_true",
        help="the post-JUL slate: FOCUS_SIGNALS x FOCUS_RULES + controls",
    )
    ap.add_argument(
        "--model", help="YYYY-MM of the CRR model to use when the delivery month's is not in hand"
    )
    ap.add_argument(
        "--dump",
        action="store_true",
        help="dry run only: also write every candidate's signals (diagnostics)",
    )
    args = ap.parse_args()
    asof = date.fromisoformat(args.asof)
    y, m = map(int, args.delivery.split("-"))
    my, mm = map(int, (args.model or args.delivery).split("-"))
    tag = f"{my}.{MON[mm - 1]}.Monthly.Auction"
    M = REF / "crr_models"
    raw = next(M.glob(f"Common_{tag}_*_{args.tou}_Common_NetworkModel.RAW"))
    built = open(raw, encoding="latin-1").read(400).split("\n")[2].strip()[:8]
    if date(int(built[:4]), int(built[4:6]), int(built[6:8])) > asof:
        raise SystemExit(f"model built {built}, after asof {asof}")
    g = Grid(raw)
    mp = Mapper(g, raw)
    pairs = defaultdict(list)
    for n, b in enumerate(g.br):
        pairs[(min(b["i"], b["j"]), max(b["i"], b["j"]))].append((b["ckt"], n))
    mon_br = {}
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
                    mon_br[n] = rt
    idxs = sorted(mon_br)
    rates = np.array([mon_br[n][0] for n in idxs])
    erates = np.array([mon_br[n][1] or mon_br[n][0] for n in idxs])
    # this month's contingency list only (later months' files postdate asof)
    conts = defaultdict(set)
    for r in csv.DictReader(open(next(M.glob(f"Common_Contingencies_{tag}_*.CSV")))):
        conts[r["Contingency"]].update(device_branches(g, r["DeviceName"], pairs))
    zone_masks = []
    for zn in sorted(set(ZONE.values())):
        mk = np.zeros(len(g.ids), dtype=bool)
        for lz, bs in mp.lz.items():
            if ZONE.get(lz) == zn:
                for b in bs:
                    mk[g.idx[b]] = True
        zone_masks.append(mk)
    hist0 = asof - timedelta(days=100)
    analog = month_days(y - 1, m)
    # the latest 30 days of disclosed DAM injections (filter + "recent" signal)
    recent = [asof - timedelta(days=60 + k) for k in range(30, 0, -1)]
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        # planned outages known by asof that cover the delivery month (>=50% derate)
        drop = defaultdict(set)
        dmonth = month_days(y, m)
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
        print(
            f"model {raw.name} (built {built}); analog {analog[0]}..{analog[-1]}; planned-outage drops: "
            f"{len(set().union(*drop.values())) if drop else 0} resources",
            flush=True,
        )
        ah, AP = injections(c, g, mp, analog, args.tou, drop, asof)
        rh, RP = injections(c, g, mp, recent, args.tou, None, asof)
        binds = c.execute(
            """select constraint_name, from_station, to_station, from_kv, sum(shadow_price)
                               from dam_constraints where delivery_date between %s and %s and hour_ending between 7 and 22
                              group by 1,2,3,4""",
            (hist0, asof - timedelta(days=1)),
        ).fetchall()
        # the two latest monthly auctions before the delivery month whose results
        # were posted by asof (compared as dates - auction names do not sort)
        prev = c.execute(
            "select auction_name, file_name from crr_auctions where report_type='monthly'"
        ).fetchall()
        posted = {
            a: f.split(".")[3][:8]
            for a, f in prev
            if a.endswith("Monthly") and len(f.split(".")) > 3
        }
        months_sorted = sorted(
            (a for a in posted if a[:3] in MON and a[3:7].isdigit()),
            key=lambda a: (int(a[3:7]), MON.index(a[:3])),
        )
        prior = [
            a
            for a in months_sorted
            if (int(a[3:7]), MON.index(a[:3]) + 1) < (y, m) and posted[a] <= asof.strftime("%Y%m%d")
        ][-2:]
        print(f"prior auctions: {prior}", flush=True)
        last_auc = prior[-1]
        clear = {
            sp: float(v)
            for sp, v in c.execute(
                """select settlement_point, shadow_price from crr_point_prices
                                                        where auction_name=%s and time_of_use=%s""",
                (last_auc, args.tou),
            )
        }

        # load growth: day-ahead SystemTotal forecasts for the 30 days to asof vs a year earlier
        def mean_load(d0, d1):
            xs = [
                x
                for (vals,) in c.execute(
                    """select vals from ercot_forecast_vintages where product='NP3-561-CD' and series='SystemTotal'
                        and delivery_date between %s and %s and posted_at::date = delivery_date - 1""",
                    (d0, d1),
                )
                for x in (vals or [])
                if x is not None
            ]
            return statistics.mean(xs) if xs else None

        l_now = mean_load(asof - timedelta(days=30), asof - timedelta(days=1))
        l_then = mean_load(asof - timedelta(days=395), asof - timedelta(days=366))
        growth = l_now / l_then if l_now and l_then else 1.0
        SCEN["grow"] = (0.0, growth - 1.0)
        print(f"load growth: {growth:.3f} (30 days to asof vs a year earlier)", flush=True)
        cands = c.execute(
            """select distinct source, sink from crr_awards where auction_name = any(%s)
                               and hedge_type='OBL' and bid_type='BUY' and time_of_use=%s""",
            (prior, args.tou),
        ).fetchall()
        price = defaultdict(dict)
        nodes = sorted({x for p in cands for x in p})
        for i in range(0, len(nodes), 100):  # batches: one big query can time out
            for sp, d, he, pr in c.execute(
                """select settlement_point, delivery_date, hour_ending, price from dam_spp
                    where settlement_point = any(%s) and delivery_date between %s and %s""",
                (nodes[i : i + 100], hist0, asof - timedelta(days=1)),
            ):
                if tou_of(d, he) == args.tou:
                    price[sp][(d, he)] = float(pr)
    hours_hist = len({k for v in price.values() for k in v})

    pos_idx = {n: k for k, n in enumerate(idxs)}
    n1 = None  # built after the screening pass

    def loading(hours, P, scen, zones=None, contingencies=True):
        """hours x monitored loading (worst of base case vs base rating and
        every contingency vs emergency rating), flow sign, and per screened
        element the contingency that was worst most often (-1 = base case)."""
        L = np.zeros((len(hours), len(idxs)))
        S = np.zeros((len(hours), len(idxs)))
        use = contingencies and n1 is not None
        if use:
            sc = np.array([pos_idx[n] for n in n1.screen])
            er = erates[sc].astype(np.float32)[:, None]
            worst = np.full((len(hours), len(sc)), -1, dtype=np.int32)
        ix = np.array(idxs)
        for t, h in enumerate(hours):
            fl = (n1 or base_n1).flows(compose(P[h], scen, zones))
            fm = fl[ix]
            L[t], S[t] = np.abs(fm) / rates, np.sign(fm)
            if use:
                pc = n1.post(fl)
                ld = np.abs(pc) / er
                k = ld.argmax(axis=1)
                lk = ld[np.arange(len(sc)), k]
                better = lk > L[t, sc]
                L[t, sc] = np.where(better, lk, L[t, sc])
                S[t, sc] = np.where(better, np.sign(pc[np.arange(len(sc)), k]), S[t, sc])
                worst[t] = np.where(better, k, -1)
        mode = {}
        if use:
            for r, n in enumerate(n1.screen):
                v = worst[:, r]
                mode[n] = int(np.bincount(v + 1).argmax()) - 1
        return L, S, mode

    # binding history -> model branches (stations/kV); used for the filter and for $ values
    bound_val = defaultdict(float)
    for _name, fs, ts, _kv, spv in binds:
        A = {b for s in (fs,) if s for b in mp.sub.get(s, set())} or (
            {b for b in g.idx if g.buses[b]["name"].upper().startswith(fs.upper())} if fs else set()
        )
        Bs = {b for s in (ts,) if s for b in mp.sub.get(s, set())} or (
            {b for b in g.idx if g.buses[b]["name"].upper().startswith(ts.upper())} if ts else set()
        )
        for n, br in enumerate(g.br):
            if (br["i"] in A and br["j"] in Bs) or (br["j"] in A and br["i"] in Bs):
                bound_val[n] += float(spv or 0) / max(hours_hist, 1)
    pos = {n for n in bound_val if n in mon_br}
    med = statistics.median([v for v in bound_val.values() if v > 0]) if bound_val else 0.0
    # base-case pass on the analog picks the elements to screen for contingencies:
    # p95 >= 0.4 or any binding history, at most 2500
    base_n1 = N1.__new__(N1)
    f0, gk0, _c0, _ = g.solver(frozenset())
    base_n1.g, base_n1.f, base_n1.gkeep = g, f0, gk0
    base_n1.I = np.array([g.idx[b["i"]] for b in g.br])
    base_n1.J = np.array([g.idx[b["j"]] for b in g.br])
    base_n1.X = np.array([b["x"] for b in g.br])
    L0, S0, _ = loading(ah, AP, "base", contingencies=False)
    p0 = np.percentile(L0, 95, axis=0)
    screen = [idxs[k] for k in np.argsort(-p0) if p0[k] >= 0.4 or idxs[k] in pos][:2500]
    n1 = N1(g, screen, conts)
    print(
        f"contingency screen: {len(screen)} elements x {len(n1.names)} contingencies "
        f"({n1.partial} would cut off a tap: modelled without the cutting link; "
        f"{n1.skipped} cut off a single bus: skipped)",
        flush=True,
    )
    RL, RS, Rmode = loading(rh, RP, "base")
    r95 = np.percentile(RL, 95, axis=0)
    hot_never = {idxs[k] for k in range(len(idxs)) if r95[k] >= HOT and idxs[k] not in pos}

    def predict(L, S, mode, filt, scale=None):
        p95 = np.percentile(L, 95, axis=0)
        sgn = np.sign(np.median(S, axis=0) + 1e-9)
        order = [k for k in np.argsort(-p95) if not (filt and idxs[k] in hot_never)][:TOPK]
        sc = scale if scale is not None else np.ones(len(idxs))
        return [
            (idxs[k], sgn[k], bound_val.get(idxs[k], 0.5 * med) * sc[k], mode.get(idxs[k], -1))
            for k in order
        ]

    # a weather scenario rescales each element's $ by the square of its mean
    # loading there versus in the base analog, clipped to 0.25x..4x
    preds, mean_l = {}, {}
    for scen in SCEN:
        L, S, mode = loading(ah, AP, scen)
        mean_l[scen] = L.mean(axis=0) + 1e-6
        scale = None if scen == "base" else np.clip((mean_l[scen] / mean_l["base"]) ** 2, 0.25, 4.0)
        preds[f"phys_{scen}"] = predict(L, S, mode, True, scale)
        if scen == "base":
            preds["phys_nofilter"] = predict(L, S, mode, False)
        print(f"  scenario {scen} done", flush=True)
    L, S, mode = loading(ah, AP, "base", zones=zone_masks)
    preds["phys_local"] = predict(L, S, mode, True)
    preds["phys_n0"] = predict(L0, S0, {}, True)
    preds["phys_recent"] = predict(RL, RS, Rmode, True)
    pb = preds["phys_base"]
    print(
        f"monitored {len(idxs)}; bound in 100d to asof {len(pos)}; hot-never filtered {len(hot_never)}; "
        f"base binders {len(pb)} ({sum(1 for p in pb if p[0] in pos)} with binding history)",
        flush=True,
    )
    base_rows = {}

    def brow(n):
        if n not in base_rows:
            base_rows[n] = ptdf_row(g, n)
        return base_rows[n]

    # shift factors in the state that binds: after the element's usual worst
    # contingency, PTDF'_m = PTDF_m + W_c[m] . PTDF_K
    srow = {n: r for r, n in enumerate(n1.screen)}
    rows = {}
    for pr in preds.values():
        for n, _, _, ci in pr:
            if (n, ci) in rows:
                continue
            r = brow(n)
            if ci >= 0:
                st = n1.starts[ci]
                K = n1.members[ci]
                w = n1.W[srow[n], st : st + len(K)]
                r = r + sum(float(wk) * brow(k) for wk, k in zip(w, K, strict=True))
            rows[(n, ci)] = r

    def sp_ptdf(sp, key):
        w = mp.spread(sp)
        return None if not w else sum(rows[key][g.idx[b]] * f for b, f in w.items())

    def hist(src, snk, since):
        a, b = price.get(src, {}), price.get(snk, {})
        v = [b[k] - a[k] for k in a if k in b and k[0] >= since]
        return statistics.mean(v) if v else None

    # market anchor: what candidate paths paid against their clearing price in
    # the delivery months completed inside the history window (pooled $/$)
    done_months = []
    d0 = hist0.replace(day=1)
    while d0 < asof:
        last = month_days(d0.year, d0.month)[-1]
        if d0 >= hist0 and last < asof:
            done_months.append(d0)
        d0 = last + timedelta(days=1)
    num = den = 0.0
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        for d0 in done_months:
            cl = {
                sp: float(v)
                for sp, v in c.execute(
                    "select settlement_point, shadow_price from crr_point_prices where auction_name=%s and time_of_use=%s",
                    (f"{MON[d0.month - 1]}{d0.year}Monthly", args.tou),
                )
            }
            for src, snk in cands:
                if excluded(src) or excluded(snk) or src not in cl or snk not in cl:
                    continue
                ec = cl[src] - cl[snk]
                if ec < MIN_CLEAR:
                    continue
                a_, b_ = price.get(src, {}), price.get(snk, {})
                v = [
                    b_[k] - a_[k]
                    for k in a_
                    if k in b_ and (k[0].year, k[0].month) == (d0.year, d0.month)
                ]
                if v:
                    num += statistics.mean(v)
                    den += ec
    R = num / den if den else 1.0
    print(
        f"market anchor: paths paid {R:.2f}x their clearing price in {[str(d)[:7] for d in done_months]}",
        flush=True,
    )

    # signal -> {(src, snk): (expected $/MWh, expected clearing)}
    sig = defaultdict(dict)
    phys = defaultdict(dict)
    cf = {}
    for src, snk in cands:
        if src not in clear or snk not in clear or excluded(src) or excluded(snk):
            continue
        exp_clear = clear[src] - clear[snk]
        if CF_BAND[0] <= exp_clear <= CF_BAND[1]:
            pr = preds["phys_base"]
            a = [sp_ptdf(src, (n, ci)) for n, _, _, ci in pr]
            b = [sp_ptdf(snk, (n, ci)) for n, _, _, ci in pr]
            if all(x is not None for x in a + b):
                cf[(src, snk)] = (
                    sum(
                        val * sg * (x - y) for (_, sg, val, _ci), x, y in zip(pr, a, b, strict=True)
                    ),
                    exp_clear,
                )
        if exp_clear < MIN_CLEAR:
            continue  # no counterflow, no penny paths
        for name in ANCHOR_PHYS:
            pr = preds[name]
            a = [sp_ptdf(src, (n, ci)) for n, _, _, ci in pr]
            b = [sp_ptdf(snk, (n, ci)) for n, _, _, ci in pr]
            if all(x is not None for x in a + b):
                phys[name][(src, snk)] = (
                    sum(
                        val * sg * (x - y) for (_, sg, val, _ci), x, y in zip(pr, a, b, strict=True)
                    ),
                    exp_clear,
                )
        sig["market"][(src, snk)] = (R * exp_clear, exp_clear)
        h100 = hist(src, snk, hist0)
        if h100 is not None:
            sig["hist100"][(src, snk)] = (h100, exp_clear)
    wx = [phys[f"phys_{s_}"] for s_ in WEATHER]
    phys["phys_robust"] = {
        k: (min(d[k][0] for d in wx), v[1]) for k, v in wx[0].items() if all(k in d for d in wx)
    }
    sig["phys_base"] = dict(phys["phys_base"])  # physics $ as the whole value: comparison only
    sig["phys_windy"] = dict(phys["phys_windy"])
    sig["phys_recent"] = dict(phys["phys_recent"])
    # physics as a veto: paths whose physics edge (value - expected clearing) is in
    # the bottom VETO_Q of candidates are dropped from the market and random baskets
    edges = {k: v - ec for k, (v, ec) in phys["phys_base"].items()}
    cut = float(np.quantile(list(edges.values()), VETO_Q)) if edges else None
    vetoed = {k for k, e in edges.items() if cut is not None and e <= cut}
    sig["market_veto"] = {k: v for k, v in sig["market"].items() if k not in vetoed}
    print(f"physics veto: {len(vetoed)} of {len(edges)} candidates (edge <= {cut})", flush=True)
    # auction-anchored: the market's value tilted by physics. z = the path's
    # physics value standardised across candidates, clipped to +-2.
    for name in ANCHORED:
        vals = phys[name]
        if len(vals) < 2:
            continue
        mu = statistics.mean(v for v, _ in vals.values())
        sd = statistics.pstdev(v for v, _ in vals.values()) or 1.0
        for k in TILTS if name == "phys_base" else (0.5,):
            tag_ = f"anch{int(k * 100)}_{name[5:]}"
            for key, (v, ec) in vals.items():
                z = max(-2.0, min(2.0, (v - mu) / sd))
                sig[tag_][key] = (R * ec * (1 + k * z), ec)

    def book(vals, margin, cap, maxp=None):
        out = [
            dict(
                source=src,
                sink=snk,
                tou=args.tou,
                mw=MW,
                limit=round(v / margin, 2),
                exp_value=round(v, 4),
                exp_clear=round(ec, 4),
                ratio=round(v / ec, 2),
            )
            for (src, snk), (v, ec) in vals.items()
            if v >= margin * ec and (maxp is None or ec <= maxp)
        ]
        # rank by $ edge (value - clearing); at most NODE_CAP paths per source / sink
        out.sort(key=lambda r: (-(r["exp_value"] - r["exp_clear"]), r["source"], r["sink"]))
        kept, ns, nk = [], defaultdict(int), defaultdict(int)
        for r in out:
            if ns[r["source"]] < NODE_CAP and nk[r["sink"]] < NODE_CAP:
                kept.append(r)
                ns[r["source"]] += 1
                nk[r["sink"]] += 1
            if len(kept) == cap:
                break
        return kept

    books = {}
    for sname in sorted(sig):
        for rname, (margin, cap, maxp) in RULES.items():
            books[f"{sname}__{rname}"] = book(sig[sname], margin, cap, maxp)
    # counterflow (paid to hold): only clear if paid >= CF_KEEP of the last price

    def cf_row(src, snk, v, ec):
        return dict(
            source=src,
            sink=snk,
            tou=args.tou,
            mw=MW,
            limit=round(CF_KEEP * ec, 2),
            exp_value=None if v is None else round(v, 4),
            exp_clear=round(ec, 4),
            ratio=None,
        )

    ranked = sorted(
        ((v - ec, k, v, ec) for k, (v, ec) in cf.items() if v > ec), key=lambda t: (-t[0], t[1])
    )
    kept, ns, nk = [], defaultdict(int), defaultdict(int)
    for _e, (src, snk), v, ec in ranked:
        if ns[src] < NODE_CAP and nk[snk] < NODE_CAP and len(kept) < MAX_BIDS:
            kept.append(cf_row(src, snk, v, ec))
            ns[src] += 1
            nk[snk] += 1
    books["cf_phys__keep75"] = kept
    rng_cf = random.Random(int(hashlib.sha256((args.delivery + "cf").encode()).hexdigest(), 16))
    books["cf_random__keep75"] = [
        cf_row(src, snk, None, ec)
        for (src, snk), (_v, ec) in rng_cf.sample(sorted(cf.items()), min(MAX_BIDS, len(cf)))
    ]
    # random control: same filtered candidates, bid 1.5x expected clearing, seeded by month
    pool = sorted({k: ec for k, (_, ec) in sig["market"].items()}.items())
    rng = random.Random(int(hashlib.sha256(args.delivery.encode()).hexdigest(), 16))
    books["random__control"] = [
        dict(
            source=src,
            sink=snk,
            tou=args.tou,
            mw=MW,
            limit=round(1.5 * ec, 2),
            exp_value=None,
            exp_clear=round(ec, 4),
            ratio=None,
        )
        for (src, snk), ec in rng.sample(pool, min(MAX_BIDS, len(pool)))
    ]
    pool_v = [x for x in pool if x[0] not in vetoed]
    rng_v = random.Random(int(hashlib.sha256((args.delivery + "veto").encode()).hexdigest(), 16))
    books["vetorand__control"] = [
        dict(
            source=src,
            sink=snk,
            tou=args.tou,
            mw=MW,
            limit=round(1.5 * ec, 2),
            exp_value=None,
            exp_clear=round(ec, 4),
            ratio=None,
        )
        for (src, snk), ec in rng_v.sample(pool_v, min(MAX_BIDS, len(pool_v)))
    ]
    if args.focused:
        books = {
            k: v
            for k, v in books.items()
            if k in FOCUS_CONTROLS
            or (k.split("__")[0] in FOCUS_SIGNALS and k.split("__")[1] in FOCUS_RULES)
        }
    for k, rws in books.items():
        print(
            f"{k:28s} {len(rws):4d} bids; authorised ${sum(r['limit'] * MW * len(ah) for r in rws):>10,.0f}"
        )
    if args.dump and not args.freeze:
        cand_out = defaultdict(dict)
        for name, vals in [*phys.items(), ("hist100", sig["hist100"]), ("market", sig["market"])]:
            for (src, snk), (v, ec) in vals.items():
                cand_out[f"{src}|{snk}"][name] = v
                cand_out[f"{src}|{snk}"]["exp_clear"] = ec
        pred_out = {
            name: [
                dict(
                    n=int(n),
                    sign=float(sg),
                    val=float(val),
                    cont=n1.names[ci] if ci >= 0 else None,
                    i=g.buses[g.br[n]["i"]]["name"],
                    j=g.buses[g.br[n]["j"]]["name"],
                    ib=g.br[n]["i"],
                    jb=g.br[n]["j"],
                    hist=n in pos,
                )
                for n, sg, val, ci in pr
            ]
            for name, pr in preds.items()
        }
        dump_dir = ARCHIVE / "out" / "preview" / f"paper_{args.delivery}_{args.tou}"
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / "signals.json").write_text(
            json.dumps(dict(R=R, cands=cand_out, preds=pred_out))
        )
    # a dry run writes an overwritable preview; --freeze seals and never rebuilds
    out = (
        ARCHIVE
        / "out"
        / ("sealed" if args.freeze else "preview")
        / f"paper_{args.delivery}_{args.tou}"
    )
    if args.freeze and out.exists():
        raise SystemExit(f"{out} exists - a frozen paper month is never rebuilt")
    out.mkdir(parents=True, exist_ok=not args.freeze)
    fields = ["source", "sink", "tou", "mw", "limit", "exp_value", "exp_clear", "ratio"]
    shas = {}
    for k, rws in books.items():
        p = out / f"{k}.csv"
        with open(p, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rws)
        shas[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    man = dict(
        delivery=args.delivery,
        asof=str(asof),
        tou=args.tou,
        model=raw.name,
        model_month=args.model or args.delivery,
        focused=args.focused,
        model_built=built,
        analog=[str(analog[0]), str(analog[-1])],
        recent=[str(recent[0]), str(recent[-1])],
        history_window=[str(hist0), str(asof - timedelta(days=1))],
        prior_auctions=prior,
        params=dict(TOPK=TOPK, MAX_BIDS=MAX_BIDS, MW=MW, HOT=HOT, RULES=RULES, SCEN=SCEN),
        sha256=shas,
    )
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    print(f"{len(books)} books -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
