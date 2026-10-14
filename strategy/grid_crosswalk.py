#!/usr/bin/env python3
"""Deterministic crosswalk between ERCOT's three naming systems.

    python strategy/grid_crosswalk.py --raw <CRR network model .RAW> [--report]

  * constraint station codes (dam_constraints.from_station / to_station, e.g. TWINBU)
  * network-model buses (PSS/E bus numbers in the CRR model RAW)
  * TPIT transmission projects (plain names, sometimes bus numbers)

The join key is ERCOT's own Settlement Points / Electrical Buses mapping
(SP_List_EB_Mapping/Settlement_Points_*.csv in REF/settlement_points_map.zip):
every electrical bus with its SUBSTATION code, VOLTAGE_LEVEL and
PSSE_BUS_NUMBER. Station code -> buses is therefore exact, and a constraint's
(from_station, to_station, kV) resolves to the model branches joining those
bus sets. Project names are matched only as a fallback, and only to stations
that have a bus at the project's voltage.

Outputs (REF): crosswalk_station_buses.json, crosswalk_constraint_branches.json,
crosswalk_projects.json. Read-only against the database.
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import REF, ROOT

load_dotenv(ROOT / ".env")


def load_sp_map():
    """substation code -> {(bus_number, kv, psse_bus_name)} from ERCOT's mapping file."""
    zf = zipfile.ZipFile(REF / "settlement_points_map.zip")
    name = next(n for n in zf.namelist() if re.search(r"Settlement_Points_.*\.csv$", n))
    st = defaultdict(set)
    bus_station = {}
    for r in csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="latin-1")):
        try:
            b = int(r["PSSE_BUS_NUMBER"])
            kv = float(r["VOLTAGE_LEVEL"])
        except (TypeError, ValueError):
            continue
        sub = (r["SUBSTATION"] or "").strip()
        if sub:
            st[sub].add((b, kv, (r["PSSE_BUS_NAME"] or "").strip()))
            bus_station[b] = sub
    return st, bus_station


def load_raw(path):
    """Buses {num: (name, kv)} and branches/transformers [(from, to, ckt, kind)] from a PSS/E v30 RAW."""
    lines = open(path, encoding="latin-1").read().split("\n")
    buses, branches, sec = {}, [], "bus"
    for ln in lines[3:]:
        if ln.startswith("0 /"):
            low = ln.lower()
            sec = ("load" if "begin load" in low else "gen" if "begin generator" in low else
                   "branch" if "begin branch" in low else "xfmr" if "begin transformer" in low else "other")
            continue
        if sec == "bus":
            m = re.match(r"\s*(\d+),'([^']*)',\s*([\d.]+)", ln)
            if m:
                buses[int(m.group(1))] = (m.group(2).strip(), float(m.group(3)))
        elif sec == "branch":
            p = ln.split(",")
            if len(p) > 3 and p[0].strip().lstrip("-").isdigit():
                branches.append((abs(int(p[0])), abs(int(p[1])), p[2].strip().strip("'"), "line"))
        elif sec == "xfmr":
            p = ln.split(",")
            # transformer records span several lines; the first starts with I,J,K
            if len(p) > 4 and p[0].strip().lstrip("-").isdigit() and p[1].strip().lstrip("-").isdigit():
                branches.append((abs(int(p[0])), abs(int(p[1])), p[3].strip().strip("'"), "xfmr"))
    return buses, branches


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    st, bus_station = load_sp_map()
    buses, branches = load_raw(args.raw)
    raw_station = {b: bus_station.get(b) for b in buses}
    print(f"mapping file: {len(st)} substations, {len(bus_station)} buses; "
          f"RAW: {len(buses)} buses ({sum(1 for v in raw_station.values() if v)} mapped to a substation), "
          f"{len(branches)} branches+transformers")

    by_pair = defaultdict(list)                      # (stationA, stationB) -> branches (sorted pair)
    for f, t, ckt, kind in branches:
        a, b = raw_station.get(f), raw_station.get(t)
        if a and b:
            by_pair[tuple(sorted((a, b)))].append((f, t, ckt, kind, buses[f][1], buses[t][1]))

    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        cons = c.execute("""select constraint_name, from_station, to_station, max(from_kv), sum(shadow_price)
                              from dam_constraints where from_station is not null
                             group by 1, 2, 3""").fetchall()
        projects = c.execute("""select project_number, phase, from_location, to_location,
                                       coalesce(title, '') || ' ' || coalesce(description, ''), voltage_kv, county_from,
                                       actual_in_service, projected_in_service, sheet
                                  from transmission_projects where report_date = (select max(report_date) from transmission_projects)""").fetchall()

    # constraints -> model branches
    out_c, hit_c, money_hit, money_all = {}, 0, 0.0, 0.0
    for name, fs, ts, kv, sp in cons:
        sp = float(sp or 0)
        money_all += sp
        cands = by_pair.get(tuple(sorted((fs, ts or fs))), [])
        if kv:
            cands = [x for x in cands if abs(x[4] - float(kv)) < 1 or abs(x[5] - float(kv)) < 1] or cands
        if cands:
            hit_c += 1
            money_hit += sp
        out_c[f"{name}|{fs}|{ts}"] = [list(x[:4]) for x in cands]
    print(f"constraints (name+stations): {len(cons)}; resolved to a model branch: {hit_c} "
          f"({100 * hit_c / len(cons):.0f}%), covering {100 * money_hit / money_all:.0f}% of all shadow-price dollars")

    # projects -> stations: bus numbers first (exact), names second (voltage-filtered)
    sub_kv = {s: {kv for _, kv, _ in v} for s, v in st.items()}

    def squash(s):
        return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

    con_stations = {s for _, fs, ts, _, _ in cons for s in (fs, ts) if s}
    out_p, n_bus, n_name = {}, 0, 0
    for pn, ph, fl, tl, _text, kv, _county, ais, pis, sheet in projects:
        found, how = set(), None
        for n in re.findall(r"\b(\d{3,6})\b", f"{fl or ''} {tl or ''}"):
            s = bus_station.get(int(n)) or raw_station.get(int(n))
            if s:
                found.add(s); how = "bus"
        if not found:
            for nm in (fl, tl):
                q = squash(nm)
                if len(q) < 4:
                    continue
                pool = [s for s in st if (not kv or any(abs(k - float(kv)) < 1 for k in sub_kv[s]))]
                exact = [s for s in pool if len(s) >= 4 and (q.startswith(s) or s.startswith(q[:6]))]
                if exact:
                    found |= set(exact); how = "name"
                else:
                    best = difflib.get_close_matches(q[:8], pool, n=1, cutoff=0.82)
                    if best:
                        found.add(best[0]); how = "name~"
        if how == "bus":
            n_bus += 1
        elif how:
            n_name += 1
        out_p[f"{pn}|{ph}"] = dict(stations=sorted(found), how=how, near_constraint=bool(found & con_stations),
                                   kv=float(kv) if kv else None, sheet=sheet,
                                   in_service=str(ais or pis) if (ais or pis) else None)
    near = sum(1 for v in out_p.values() if v["near_constraint"])
    print(f"projects (TPIT {len(projects)} rows): by bus number {n_bus}, by name {n_name}, "
          f"none {len(projects) - n_bus - n_name}; touching a constrained station: {near}")

    json.dump({s: sorted(v) for s, v in st.items()}, open(REF / "crosswalk_station_buses.json", "w"))
    json.dump(out_c, open(REF / "crosswalk_constraint_branches.json", "w"))
    json.dump(out_p, open(REF / "crosswalk_projects.json", "w"), indent=0)
    if args.report:
        miss = sorted(((float(sp or 0), n, f, t) for n, f, t, k, sp in cons
                       if not out_c[f"{n}|{f}|{t}"]), reverse=True)[:15]
        print("largest unresolved constraints ($ shadow):")
        for sp, n, f, t in miss:
            print(f"   {n[:24]:24} {f} -> {t}  ${sp:,.0f}  stations in map: {f in st}/{t in st}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
