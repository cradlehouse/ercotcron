#!/usr/bin/env python3
"""Month-ahead congestion forecast, frozen before an auction cutoff.

    python strategy/month_forecast.py --month 2026-11 --cutoff 2026-10-12 --out DIR

Information set: DAM constraints, node spreads and outage reports up to
--cutoff, TPIT (latest release before cutoff), path exposure fitted on the
12 months ending at cutoff (REF/path_exposure.json; refuses a later window).

Constraint forecast (mean peak-hour DAM shadow per day in the delivery month):
  H  history     - mean over the 12-month fit window
  P  persistence - mean over the last 6 weeks (cutoff-41d .. cutoff)
  L  lifecycle   - VANISHED (base-span sum >= $50k and recent rate <= 25% of
                   base rate) -> 0; RISING (recent >= 3x base and >= $10k) -> P;
                   UPGRADE (a TPIT project in service between cutoff-42d and the
                   delivery month's first day touches one of its stations) ->
                   0.5 x its otherwise-forecast value (event study: median drop
                   to ~0.51x); else H.  Base span = fit-window start .. Jul 31.
Path forecast (mean daily peak spread sink-source, $/MWh):
  H   history: the path's fit-window mean
  P/L history adjusted by each constraint's contribution x (F_c / H_c - 1)
  LO  L + Martin Lake 2 outage effect (confirmed out all of the delivery month):
      (delta_sink - delta_source) from outage_node_deltas, scaled by the share
      of fit-window days ML2 was NOT already out (avoid double counting).
Writes constraints.csv, paths.csv and manifest.json; prints SHA-256s.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import REF, ROOT

load_dotenv(ROOT / ".env")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--cutoff", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    cutoff = date.fromisoformat(args.cutoff)
    m0 = date.fromisoformat(args.month + "-01")
    ex = json.load(open(REF / "path_exposure.json"))
    w0, w1 = (date.fromisoformat(x) for x in ex["window"])
    if w1 > cutoff:
        raise SystemExit(f"exposure window ends {w1}, after cutoff {cutoff}")
    recent0 = cutoff - timedelta(days=41)
    base1 = date(cutoff.year, 7, 31)
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        agg = {}
        for n, h, p, b, nh, np_ in c.execute("""
              select constraint_name,
                sum(shadow_price) filter (where delivery_date between %(w0)s and %(w1)s),
                sum(shadow_price) filter (where delivery_date between %(r0)s and %(w1)s),
                sum(shadow_price) filter (where delivery_date between %(w0)s and %(b1)s),
                count(distinct delivery_date) filter (where delivery_date between %(w0)s and %(w1)s),
                count(distinct delivery_date) filter (where delivery_date between %(r0)s and %(w1)s)
              from dam_constraints where delivery_date between %(w0)s and %(w1)s and hour_ending between 7 and 22
              group by 1""", dict(w0=w0, w1=w1, r0=recent0, b1=base1)):
            agg[n] = (float(h or 0), float(p or 0), float(b or 0), nh or 0, np_ or 0)
        stations = defaultdict(set)
        for n, f, t in c.execute("""select distinct constraint_name, from_station, to_station from dam_constraints
                                    where delivery_date between %s and %s""", (w0, w1)):
            stations[n] |= {s for s in (f, t) if s}
        tpit = c.execute("select max(report_date) from transmission_projects where report_date <= %s", (cutoff,)).fetchone()[0]
        deltas = {sp: float(d or 0) for sp, d in c.execute(
            "select settlement_point, train_delta from outage_node_deltas where unit_code = 'MLSES_UNIT2'")}
        ml2_down = set()
        for s, e in c.execute("""select outage_start::date, coalesce(planned_end::date, outage_start::date) from resource_outages
                                 where unit_code = 'MLSES_UNIT2' and reduction_mw >= 400 and outage_start::date <= %s
                                   and coalesce(planned_end::date, outage_start::date) >= %s""", (w1, w0)):
            d = max(s, w0)
            while d <= min(e, w1):
                ml2_down.add(d)
                d += timedelta(days=1)
    nfit = (w1 - w0).days + 1
    nrec = (w1 - recent0).days + 1
    nbase = (base1 - w0).days + 1
    # projects in service between cutoff-42d and the month start, by station
    cw = json.load(open(REF / "crosswalk_projects.json"))
    up_st = set()
    for v in cw.values():
        d = v.get("in_service")
        if d and cutoff - timedelta(days=42) <= date.fromisoformat(d[:10]) <= m0:
            up_st |= set(v.get("stations") or [])
    fc, rows_c = {}, []
    for n, (h, p, b, _nh, _np) in agg.items():
        H, P, B = h / nfit, p / nrec, b / nbase
        cls = "steady"
        L = H
        if b >= 50000 and P <= 0.25 * B:
            cls, L = "vanished", 0.0
        elif p >= 10000 and P >= 3 * B:
            cls, L = "rising", P
        if cls != "vanished" and stations[n] & up_st:
            cls, L = cls + "+upgrade", 0.5 * L
        fc[n] = (H, P, L)
        rows_c.append(dict(constraint=n, cls=cls, H=round(H, 2), P=round(P, 2), L=round(L, 2),
                           stations=";".join(sorted(stations[n]))))
    frac_up = 1 - len(ml2_down) / nfit
    rows_p = []
    for k, v in ex["paths"].items():
        src, snk = k.split("|")
        base = v["value"]
        adj = {"P": 0.0, "L": 0.0}
        for cn, contrib in v["contrib"].items():
            H, P, L = fc.get(cn, (0, 0, 0))
            if H > 0:
                adj["P"] += contrib * (P / H - 1)
                adj["L"] += contrib * (L / H - 1)
        ml2 = (deltas.get(snk, 0) - deltas.get(src, 0)) * frac_up
        rows_p.append(dict(source=src, sink=snk, H=round(base, 4), P=round(base + adj["P"], 4),
                           L=round(base + adj["L"], 4), LO=round(base + adj["L"] + ml2, 4), r2=v["r2"]))
    os.makedirs(args.out, exist_ok=True)
    shas = {}
    for name, rows in (("constraints.csv", rows_c), ("paths.csv", rows_p)):
        p = os.path.join(args.out, name)
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: next(iter(r.values()))))
        shas[name] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    man = dict(month=args.month, cutoff=str(cutoff), exposure_window=ex["window"], tpit_release=str(tpit),
               ml2_down_days_in_fit=len(ml2_down), upgrade_stations=sorted(up_st),
               counts={c: sum(1 for r in rows_c if r["cls"] == c) for c in {r["cls"] for r in rows_c}},
               paths=len(rows_p), sha256=shas)
    json.dump(man, open(os.path.join(args.out, "manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
