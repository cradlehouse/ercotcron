#!/usr/bin/env python3
"""Geolocate ERCOT stations by aligning ERCOT's network with OpenStreetMap's.

    python strategy/geo_osm.py --raw <CRR network model .RAW>

ERCOT side: station graph from the CRR model (buses -> SUBSTATION via ERCOT's
Settlement_Points mapping; unmapped buses fall back to their RAW name prefix),
edges carry kV.
OSM side (REF/osm_power_tx, from scripts/fetch_osm_power.py): substations with
names, voltages and positions; transmission line ways with voltage and geometry.
Line ways are chained end to end and snapped to substations to get OSM
substation-to-substation links with kV and route length.

Matching:
  1. seeds - name evidence (abbreviation rules) + voltage compatibility, kept only
     when an ERCOT neighbour also matches an OSM neighbour at the same kV;
  2. propagation - an unmatched ERCOT station next to a confirmed one may only
     match OSM substations wired to the confirmed one's match at the same kV; a
     unique (or name-preferred) candidate is accepted. Repeated to a fixed point.
Validation: resource-node coordinates (node_coords_v2, high confidence) via
Resource_Node_to_Unit -> UNIT_SUBSTATION, scored within 20 km.
Output: REF/station_geo_osm.json {code: {lat, lon, osm_name, how}}.
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import math
import os
import re
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.common import REF
from strategy.grid_crosswalk import load_raw, load_sp_map

SNAP_KM = 0.8
WORD = {"SWITCH": "SW", "SWITCHING": "SW", "SWITCHYARD": "SW", "CREEK": "CRK", "NORTH": "N", "SOUTH": "S",
        "EAST": "E", "WEST": "W", "ROAD": "RD", "LAKE": "LK", "MOUNTAIN": "MTN", "FORT": "FT", "SAINT": "ST",
        "JUNCTION": "JCT", "SPRINGS": "SPGS", "POINT": "PT", "RANCH": "RCH", "COUNTY": "CNTY"}
DROP = {"SUBSTATION", "STATION", "SUB", "SS", "POWER", "PLANT", "THE", "OF", "ELECTRIC", "ENERGY", "CENTER",
        "TAP", "GENERATING", "SWITCHING"}


def km(a, b):
    r = math.radians
    h = math.sin(r(b[0] - a[0]) / 2) ** 2 + math.cos(r(a[0])) * math.cos(r(b[0])) * math.sin(r(b[1] - a[1]) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def volts(v):
    out = set()
    for p in re.split(r"[;,]", v or ""):
        try:
            x = float(p) / 1000.0
            if x >= 60:
                out.add(round(x))
        except ValueError:
            pass
    return out


def abbrevs(name):
    """Abbreviation variants of an OSM substation name, e.g. 'San Angelo Lake Nasworthy
    Substation' -> LAKENA..., SALAKE..., LAKENASW."""
    ws = [w for w in re.sub(r"[^A-Za-z0-9 ]", " ", name).upper().split() if w not in DROP]
    if not ws:
        return set()
    out = set()
    for start in range(min(2, len(ws))):  # optionally drop a leading city word
        sub = ws[start:]
        full = "".join(sub)
        mapped = "".join(WORD.get(w, w) for w in sub)
        for s in (full, mapped):
            out |= {s[:k] for k in range(4, 9)}
        if len(sub) >= 2:
            for a in range(2, 7):
                for b in range(1, 5):
                    out.add(sub[0][:a] + WORD.get(sub[1], sub[1])[:b])
        out |= {(s + "SW")[:k] for s in (full[:6], mapped[:6]) for k in (6, 7, 8)}
    if len(ws) >= 3:  # city initials + rest: San Angelo Mathis -> SAMATHIS
        ini = ws[0][0] + ws[1][0]
        rest = "".join(ws[2:])
        out |= {(ini + rest)[:k] for k in range(4, 9)}
    return {x for x in out if len(x) >= 4}


def load_osm():
    subs, lines = {}, {}
    for f in glob.glob(str(REF / "osm_power_tx" / "tile_*.json")):
        for e in json.load(open(f)):
            t = e.get("tags", {})
            if t.get("power") == "substation":
                c = e.get("center") or ({"lat": e.get("lat"), "lon": e.get("lon")} if "lat" in e else None)
                if c:
                    subs[(e["type"], e["id"])] = dict(name=t.get("name", ""), pos=(c["lat"], c["lon"]),
                                                      kv=volts(t.get("voltage")))
            elif t.get("power") == "line" and e.get("geometry"):
                g = [(p["lat"], p["lon"]) for p in e["geometry"]]
                lines[e["id"]] = dict(geom=g, kv=volts(t.get("voltage")))
    return subs, lines


def osm_links(subs, lines):
    """Substation-to-substation links: chain line ways through shared endpoints and
    snap endpoints within SNAP_KM of a substation."""
    grid = defaultdict(list)
    for k, s in subs.items():
        grid[(round(s["pos"][0], 1), round(s["pos"][1], 1))].append(k)

    def snap(p):
        best, bd = None, SNAP_KM
        for dx in (-0.1, 0, 0.1):
            for dy in (-0.1, 0, 0.1):
                for k in grid.get((round(p[0] + dx, 1), round(p[1] + dy, 1)), ()):
                    d = km(p, subs[k]["pos"])
                    if d < bd:
                        best, bd = k, d
        return best

    node = lambda p: ("pt", round(p[0], 4), round(p[1], 4))  # noqa: E731
    adj = defaultdict(list)  # graph node -> [(graph node, km, kv set)]
    for w in lines.values():
        g = w["geom"]
        a, b = g[0], g[-1]
        na, nb = snap(a) or node(a), snap(b) or node(b)
        length = sum(km(g[i], g[i + 1]) for i in range(len(g) - 1))
        adj[na].append((nb, length, w["kv"]))
        adj[nb].append((na, length, w["kv"]))
    links = defaultdict(dict)  # sub -> {sub: (km, kv set)}
    for s in subs:
        if s not in adj:
            continue
        stack, seen = [(s, 0.0, None)], {s}
        while stack:
            cur, dist, kv = stack.pop()
            for nxt, ln, k2 in adj[cur]:
                if nxt in seen:
                    continue
                kv2 = (kv & k2) if (kv and k2) else (kv or k2)
                if kv and k2 and not (kv & k2):
                    continue  # voltage change mid-chain: not one line
                seen.add(nxt)
                if nxt in subs:
                    if nxt != s:
                        old = links[s].get(nxt)
                        if not old or dist + ln < old[0]:
                            links[s][nxt] = (dist + ln, kv2 or set())
                elif dist + ln < 400:
                    stack.append((nxt, dist + ln, kv2))
    return links


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    args = ap.parse_args()
    _st, bus_station = load_sp_map()
    buses, branches = load_raw(args.raw)

    def station(b):
        s = bus_station.get(b)
        if s:
            return s
        m = re.match(r"[A-Z0-9]+", buses[b][0].upper()) if b in buses else None
        return m.group(0)[:8] if m else None

    E = defaultdict(set)
    skv = defaultdict(set)
    for f, t, _ckt, kind in branches:
        a, b = station(f), station(t)
        if f in buses:
            skv[a].add(round(buses[f][1]))
        if t in buses:
            skv[b].add(round(buses[t][1]))
        if a and b and a != b and kind == "line":
            E[a].add((b, round(buses[f][1])))
            E[b].add((a, round(buses[f][1])))

    subs, lines = load_osm()
    links = osm_links(subs, lines)
    print(f"ERCOT stations {len(E)}; OSM substations {len(subs)} ({sum(1 for s in subs.values() if s['name'])} named), "
          f"line ways {len(lines)}, substations with traced links {len(links)}")

    kv_ok = lambda code, k: not subs[k]["kv"] or not skv[code] or bool(subs[k]["kv"] & skv[code])  # noqa: E731
    ab = {k: abbrevs(s["name"]) for k, s in subs.items() if s["name"]}
    by_ab = defaultdict(set)
    for k, v in ab.items():
        for x in v:
            by_ab[x].add(k)
    cand = {}
    for code in E:
        c = {k for k in by_ab.get(code, ()) if kv_ok(code, k)}
        if not c and len(code) >= 5:
            c = {k for x, ks in by_ab.items() if x.startswith(code[:5]) for k in ks if kv_ok(code, k)}
        if c:
            cand[code] = c

    match, how = {}, {}
    for code, cs in cand.items():  # seeds need a neighbour agreeing through a traced OSM link
        for k in cs:
            agree = sum(1 for nb, kv in E[code] for k2 in cand.get(nb, ()) if k2 in links.get(k, {}))
            if agree >= 1 and (code not in match or agree > how.get(code, (0,))[0]):
                match[code], how[code] = k, (agree, "name+link")
    seeds = len(match)
    for _ in range(12):  # propagate through topology
        added = 0
        for code, nb in E.items():
            if code in match:
                continue
            pool = set()
            for n2, kv in nb:
                if n2 in match:
                    for k, (_ln, kvs) in links.get(match[n2], {}).items():
                        if (not kvs or kv in kvs) and kv_ok(code, k) and k not in match.values():
                            pool.add(k)
            if not pool:
                continue
            named = pool & cand.get(code, set())
            pick = named if named else pool
            if len(pick) == 1:
                match[code] = next(iter(pick))
                how[code] = (0, "link+name" if named else "link-only")
                added += 1
        if not added:
            break
    print(f"matched: {len(match)} stations ({seeds} seeds, {len(match) - seeds} by propagation; "
          f"link-only {sum(1 for v in how.values() if v[1] == 'link-only')})")

    # validation against resource-node coordinates through unit substations
    zf = zipfile.ZipFile(REF / "settlement_points_map.zip")
    rn = next(n for n in zf.namelist() if "Resource_Node_to_Unit" in n)
    unit_sub = {}
    for r in csv.DictReader(io.TextIOWrapper(zf.open(rn), encoding="latin-1")):
        unit_sub.setdefault(r["RESOURCE_NODE"], r["UNIT_SUBSTATION"])
    nc = json.load(open(REF / "node_coords_v2.json"))
    ds = []
    for node, v in nc.items():
        rec = v[0] if isinstance(v, list) else v
        s = unit_sub.get(node)
        if s in match and rec.get("confidence") == "high":
            ds.append(km((rec["lat"], rec["lon"]), subs[match[s]]["pos"]))
    if ds:
        ds.sort()
        print(f"validation vs high-confidence plant coordinates (n={len(ds)}): median {ds[len(ds)//2]:.1f} km, "
              f"within 20 km {100*sum(1 for d in ds if d <= 20)/len(ds):.0f}%, within 40 km {100*sum(1 for d in ds if d <= 40)/len(ds):.0f}%")
    con = json.load(open(REF / "crosswalk_constraint_branches.json")) if (REF / "crosswalk_constraint_branches.json").exists() else {}
    cst = {k.split("|")[1] for k in con} | {k.split("|")[2] for k in con}
    print(f"constraint stations located: {len(cst & set(match))} of {len(cst)}")
    json.dump({c: dict(lat=subs[k]["pos"][0], lon=subs[k]["pos"][1], osm_name=subs[k]["name"], how=how[c][1])
               for c, k in match.items()}, open(REF / "station_geo_osm.json", "w"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
