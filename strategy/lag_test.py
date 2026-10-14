#!/usr/bin/env python3
"""Does the CRR auction model carry a transmission upgrade before, at, or after
it goes in service? (Nodal Protocols 7.5.1(2): "for CRR Auctions held after the
month in which the element is placed into service".)

    python strategy/lag_test.py [--tou PeakWD]

Models: REF/crr_models/Common_<YYYY.MON>.Monthly.Auction_..._<TOU>_Common_NetworkModel.RAW.
Auction for delivery month D is held in month D-1. For every TPIT 'completed'
project with an actual in-service date inside the models' span, find the first
model in which a branch touching the project's stations is added or changed
(reactance or rating) relative to the previous model, and report the auction
month that carried it relative to the in-service month.
Stations come from REF/crosswalk_projects.json (bus-number matches first).
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pathlib

import psycopg
from dotenv import load_dotenv

from strategy.common import REF, ROOT
from strategy.grid_crosswalk import load_sp_map
from strategy.ptdf import parse_raw

load_dotenv(ROOT / ".env")
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tou", default="PeakWD")
    args = ap.parse_args()
    _st, bus_station = load_sp_map()
    files = sorted(REF.glob(f"crr_models/Common_*Monthly.Auction_*_{args.tou}_Common_NetworkModel.RAW"))
    models = []
    for f in files:
        m = re.search(r"Common_(\d{4})\.([A-Z]{3})\.Monthly", f.name)
        dy, dm = int(m.group(1)), MON[m.group(2)]
        held = date(dy - (dm == 1), 12 if dm == 1 else dm - 1, 1)
        stamp = open(f, encoding="latin-1").read(400).split("\n")[2].strip()
        _buses, branches = parse_raw(pathlib.Path(f))
        br = {(min(b["i"], b["j"]), max(b["i"], b["j"]), str(b["ckt"]).strip(), b["kind"]): (round(b["x"], 6), round(b["rate"], 1))
              for b in branches}
        models.append(dict(delivery=f"{dy}-{dm:02d}", held=held, built=stamp[:8], br=br))
        print(f"model {dy}-{dm:02d}: auction held {held:%b %Y}, built {stamp[:8]}, {len(br)} branches", flush=True)
    models.sort(key=lambda x: x["delivery"])
    changes = []  # per model (vs previous): set of stations touched
    for a, b in itertools.pairwise(models):
        touched = set()
        for k in set(b["br"]) | set(a["br"]):
            # topology only: a branch added or removed, or reactance moved >5%
            # (rebuild/reconductor). Ratings change seasonally almost everywhere
            # and would make every station look "changed" every month.
            xa, xb = a["br"].get(k, (None,))[0], b["br"].get(k, (None,))[0]
            if xa is None or xb is None or abs(xb - xa) > 0.05 * max(abs(xa), 1e-6):
                for bus in k[:2]:
                    s = bus_station.get(bus)
                    if s:
                        touched.add(s)
        changes.append((b, touched))
        print(f"  {a['delivery']} -> {b['delivery']}: branches changed at {len(touched)} stations", flush=True)
    cw = json.load(open(REF / "crosswalk_projects.json"))
    first, last = models[0]["held"], models[-1]["held"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        proj = c.execute("""select project_number, phase, coalesce(title, description), actual_in_service
                              from transmission_projects
                             where report_date = (select max(report_date) from transmission_projects)
                               and sheet = 'completed' and actual_in_service between %s and %s""", (first, last)).fetchall()
    res = []
    for pn, ph, title, ais in proj:
        st = set((cw.get(f"{pn}|{ph}") or {}).get("stations") or [])
        if not st:
            continue
        hit = next(((m, sorted(st & t)) for m, t in changes if st & t), None)
        res.append((ais, (title or "")[:55], sorted(st), hit))
    print(f"\nprojects in service {first:%b %Y}..{last:%b %Y} with mapped stations: {len(res)}")
    lags = []
    for ais, title, st, hit in sorted(res):
        if hit:
            m, at = hit
            lag = (m["held"].year - ais.year) * 12 + m["held"].month - ais.month
            lags.append(lag)
            print(f"  {ais}  {title:55} first change in {m['delivery']} model (held {m['held']:%b %Y}, built {m['built']}): lag {lag:+d} mo  at {at[:3]}")
        else:
            print(f"  {ais}  {title:55} no branch change found at {st[:3]}")
    if lags:
        from collections import Counter
        print("\nlag (auction-held month minus in-service month):", sorted(Counter(lags).items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
