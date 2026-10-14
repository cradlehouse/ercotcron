#!/usr/bin/env python3
"""Fetch OpenStreetMap power substations and transmission lines for Texas.

    python scripts/fetch_osm_power.py [--step 1.5]

Public Overpass API, tiled so each request stays small, one tile at a time with
a pause (shared community service). Substations come back with tags + centre
point; lines (way power=line) with tags + full geometry, which is what lets a
line be traced from one substation to another and its length measured.

Writes one JSON per tile under REF/osm_power_tx/ and skips tiles already
fetched, so an interrupted run resumes. No database writes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy.common import REF

MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
TX = (25.8, -106.7, 36.6, -93.5)  # south, west, north, east


def fetch(q: str, tries: int = 6) -> dict:
    last = None
    for attempt in range(tries):
        url = MIRRORS[attempt % len(MIRRORS)]
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "ercotcron-research/1.0 (grid topology study)"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except Exception as e:  # rate limits and timeouts are routine on Overpass
            last = e
            time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"overpass failed: {last}")


def fetch_box(s, w, n, e, depth=0) -> list:
    """One box; when the server times out on it, split into quarters (dense
    areas such as the Permian time out whole) and merge, de-duplicated by id."""
    bbox = f"{s},{w},{n},{e}"
    q = (f'[out:json][timeout:200];'
         f'(nwr["power"="substation"]({bbox}););out tags center;'
         f'(way["power"="line"]({bbox}););out tags geom;')
    try:
        return fetch(q, tries=3 if depth < 3 else 6).get("elements", [])
    except RuntimeError:
        if depth >= 3:
            raise
        ms, mw = (s + n) / 2, (w + e) / 2
        seen, out = set(), []
        for box in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
            for el in fetch_box(*box, depth=depth + 1):
                key = (el.get("type"), el.get("id"))
                if key not in seen:
                    seen.add(key)
                    out.append(el)
            time.sleep(3)
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=1.5)
    args = ap.parse_args()
    out = REF / "osm_power_tx"
    out.mkdir(parents=True, exist_ok=True)
    s0, w0, n0, e0 = TX
    tiles = []
    lat = s0
    while lat < n0:
        lon = w0
        while lon < e0:
            tiles.append((round(lat, 3), round(lon, 3), round(min(lat + args.step, n0), 3), round(min(lon + args.step, e0), 3)))
            lon += args.step
        lat += args.step
    print(f"{len(tiles)} tiles", flush=True)
    for k, (s, w, n, e) in enumerate(tiles):
        f = out / f"tile_{s}_{w}.json"
        if f.exists():
            continue
        els = fetch_box(s, w, n, e)
        json.dump(els, open(f, "w"))
        subs = sum(1 for x in els if x.get("tags", {}).get("power") == "substation")
        print(f"[{k + 1}/{len(tiles)}] {s},{w},{n},{e}: {subs} substations, {len(els) - subs} line ways", flush=True)
        time.sleep(4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
