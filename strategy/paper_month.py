#!/usr/bin/env python3
"""Walk-forward paper bid for ONE monthly auction, built only from data known
at the auction cutoff (replay-plan addendum, 15 Oct 2026).

    python strategy/paper_month.py --delivery 2026-02 --asof 2026-01-11 [--tou PeakWD] [--freeze]

Every run builds a slate of books from the same candidates and clearing
estimates, so one month tests many ideas at once (signal x bid rule):

Signals (expected $/MWh for each path):
  phys_base    analog month (same month last year, 60-Day DAM Disclosure, all
               dated <= asof-60) minus units on planned outages known by asof;
               DC flows on the delivery month's CRR model; top-K elements by
               95th-percentile loading after the hot-never filter; each worth
               its average peak DAM shadow over the 100 days to asof (else half
               the median); path value = sum of value x shift-factor difference.
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
# bid rules: name -> (required value / clearing, max bids); limit = value / ratio
RULES = {
    "m125": (1.25, MAX_BIDS),
    "m150": (1.5, MAX_BIDS),
    "m200": (2.0, MAX_BIDS),
    "wide110": (1.10, 150),
}
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
    P = {h: (np.zeros(nb), np.zeros(nb), np.zeros(nb)) for h in hours}
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
        if res in drop.get(d, ()):
            continue
        for k, v in enumerate(arr):
            if (d, k + 1) in hs and v:
                add(P[(d, k + 1)][2 if rt in GAS else 0], sp, v)
        if rt == "WIND" and hsl:
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


def compose(parts, scen):
    """Net injection vector for one hour under a weather scenario."""
    other, wcap, gas, shape = parts
    dw, xl = SCEN[scen]
    Wc, G = wcap.sum(), gas.sum()
    inj = other + gas
    if Wc > 0 and dw:
        inj = inj + dw * wcap / Wc
    if G > 0 and (dw or xl):
        need = G - dw + xl * (other.sum() + G)
        inj = inj + (max(need, 0.2 * G) / G - 1) * gas
    return inj - inj.sum() * shape


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
    args = ap.parse_args()
    asof = date.fromisoformat(args.asof)
    y, m = map(int, args.delivery.split("-"))
    tag = f"{y}.{MON[m - 1]}.Monthly.Auction"
    M = REF / "crr_models"
    raw = next(M.glob(f"Common_{tag}_*_{args.tou}_Common_NetworkModel.RAW"))
    built = open(raw, encoding="latin-1").read(400).split("\n")[2].strip()[:8]
    if date(int(built[:4]), int(built[4:6]), int(built[6:8])) > asof:
        raise SystemExit(f"model built {built}, after asof {asof}")
    g = Grid(raw)
    mp = Mapper(g, raw)
    mon = {}
    for r in csv.DictReader(
        open(next(M.glob(f"Common_MonitoredLinesAndTransformers_{tag}_*.CSV")))
    ):
        if r["TimeOfUse"] == args.tou:
            p = r["DeviceName"].split()
            try:
                mon[(min(int(p[0]), int(p[2])), max(int(p[0]), int(p[2])), p[4])] = float(
                    r["BaseCaseRating"]
                )
            except (ValueError, IndexError):
                pass
    mon_br = {n: rate for key, rate in mon.items() for n in g.key.get(key, []) if rate}
    idxs = sorted(mon_br)
    rates = np.array([mon_br[n] for n in idxs])
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
            """select coalesce(resource_name, unit_code), outage_start::date,
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
        prev = c.execute(
            """select auction_name from crr_auctions where report_type='monthly' and auction_name < %s
                            order by 1""",
            (f"{MON[m - 1]}{y}Monthly",),
        ).fetchall()
        months_sorted = sorted({a for (a,) in prev}, key=lambda a: (int(a[3:7]), MON.index(a[:3])))
        prior = [a for a in months_sorted if (int(a[3:7]), MON.index(a[:3]) + 1) < (y, m)][-2:]
        last_auc = prior[-1]
        clear = {
            sp: float(v)
            for sp, v in c.execute(
                """select settlement_point, shadow_price from crr_point_prices
                                                        where auction_name=%s and time_of_use=%s""",
                (last_auc, args.tou),
            )
        }
        cands = c.execute(
            """select distinct source, sink from crr_awards where auction_name = any(%s)
                               and hedge_type='OBL' and bid_type='BUY' and time_of_use=%s""",
            (prior, args.tou),
        ).fetchall()
        price = defaultdict(dict)
        nodes = sorted({x for p in cands for x in p})
        for sp, d, he, pr in c.execute(
            """select settlement_point, delivery_date, hour_ending, price from dam_spp
                where settlement_point = any(%s) and delivery_date between %s and %s""",
            (nodes, hist0, asof - timedelta(days=1)),
        ):
            if tou_of(d, he) == args.tou:
                price[sp][(d, he)] = float(pr)
    hours_hist = len({k for v in price.values() for k in v})

    def loading(hours, P, scen):
        L = np.zeros((len(hours), len(idxs)))
        S = np.zeros((len(hours), len(idxs)))
        for t, h in enumerate(hours):
            fl = g.flows(compose(P[h], scen), frozenset(), idxs)
            L[t], S[t] = np.abs(fl) / rates, np.sign(fl)
        return L, S

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
    RL, RS = loading(rh, RP, "base")
    r95 = np.percentile(RL, 95, axis=0)
    hot_never = {idxs[k] for k in range(len(idxs)) if r95[k] >= HOT and idxs[k] not in pos}

    def predict(L, S, filt, scale=None):
        p95 = np.percentile(L, 95, axis=0)
        sgn = np.sign(np.median(S, axis=0) + 1e-9)
        order = [k for k in np.argsort(-p95) if not (filt and idxs[k] in hot_never)][:TOPK]
        sc = scale if scale is not None else np.ones(len(idxs))
        return [(idxs[k], sgn[k], bound_val.get(idxs[k], 0.5 * med) * sc[k]) for k in order]

    # a weather scenario rescales each element's $ by the square of its mean
    # loading there versus in the base analog, clipped to 0.25x..4x
    preds, mean_l = {}, {}
    for scen in SCEN:
        L, S = loading(ah, AP, scen)
        mean_l[scen] = L.mean(axis=0) + 1e-6
        scale = None if scen == "base" else np.clip((mean_l[scen] / mean_l["base"]) ** 2, 0.25, 4.0)
        preds[f"phys_{scen}"] = predict(L, S, True, scale)
        if scen == "base":
            preds["phys_nofilter"] = predict(L, S, False)
    preds["phys_recent"] = predict(RL, RS, True)
    pb = preds["phys_base"]
    print(
        f"monitored {len(idxs)}; bound in 100d to asof {len(pos)}; hot-never filtered {len(hot_never)}; "
        f"base binders {len(pb)} ({sum(1 for p in pb if p[0] in pos)} with binding history)",
        flush=True,
    )
    rows = {n: ptdf_row(g, n) for pr in preds.values() for n, _, _ in pr}

    def sp_ptdf(sp, n):
        w = mp.spread(sp)
        return None if not w else sum(rows[n][g.idx[b]] * f for b, f in w.items())

    def hist(src, snk, since):
        a, b = price.get(src, {}), price.get(snk, {})
        v = [b[k] - a[k] for k in a if k in b and k[0] >= since]
        return statistics.mean(v) if v else None

    # signal -> {(src, snk): (expected $/MWh, expected clearing)}
    sig = defaultdict(dict)
    for src, snk in cands:
        if src not in clear or snk not in clear:
            continue
        exp_clear = clear[src] - clear[snk]
        if exp_clear <= 0:
            continue  # no counterflow
        pv = {}
        for name, pr in preds.items():
            a = [sp_ptdf(src, n) for n, _, _ in pr]
            b = [sp_ptdf(snk, n) for n, _, _ in pr]
            if all(x is not None for x in a + b):
                pv[name] = sum(
                    val * sg * (x - y) for (_, sg, val), x, y in zip(pr, a, b, strict=True)
                )
        for name, v in pv.items():
            sig[name][(src, snk)] = (v, exp_clear)
        wx = [pv[f"phys_{s}"] for s in SCEN if f"phys_{s}" in pv]
        if len(wx) == len(SCEN):
            sig["phys_robust"][(src, snk)] = (min(wx), exp_clear)
            sig["phys_wxavg"][(src, snk)] = (statistics.mean(wx), exp_clear)
        h100, h30 = hist(src, snk, hist0), hist(src, snk, asof - timedelta(days=30))
        if h100 is not None:
            sig["hist100"][(src, snk)] = (h100, exp_clear)
            if "phys_base" in pv:
                sig["consensus"][(src, snk)] = (min(h100, pv["phys_base"]), exp_clear)
        if h30 is not None:
            sig["hist30"][(src, snk)] = (h30, exp_clear)

    def book(vals, margin, cap):
        out = [
            dict(
                source=src,
                sink=snk,
                tou=args.tou,
                mw=MW,
                limit=round(v / margin, 2),
                exp_value=round(v, 4),
                exp_clear=round(ec, 4),
                ratio=round(v / max(ec, 0.05), 2),
            )
            for (src, snk), (v, ec) in vals.items()
            if v >= margin * max(ec, 0.05)
        ]
        return sorted(out, key=lambda r: (-r["ratio"], r["source"], r["sink"]))[:cap]

    books = {}
    for sname in sorted(sig):
        for rname, (margin, cap) in RULES.items():
            books[f"{sname}__{rname}"] = book(sig[sname], margin, cap)
    # random control: same candidates, bid 1.5x expected clearing, seeded by month
    pool = sorted({k: ec for vals in sig.values() for k, (_, ec) in vals.items()}.items())
    rng = random.Random(int(hashlib.sha256(args.delivery.encode()).hexdigest(), 16))
    books["random__control"] = [
        dict(
            source=src,
            sink=snk,
            tou=args.tou,
            mw=MW,
            limit=round(1.5 * max(ec, 0.05), 2),
            exp_value=None,
            exp_clear=round(ec, 4),
            ratio=None,
        )
        for (src, snk), ec in rng.sample(pool, min(MAX_BIDS, len(pool)))
    ]
    for k, rws in books.items():
        print(
            f"{k:28s} {len(rws):4d} bids; authorised ${sum(r['limit'] * MW * len(ah) for r in rws):>10,.0f}"
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
