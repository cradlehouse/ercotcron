#!/usr/bin/env python3
"""Diff two CRR network models: what topology changed between auctions?

    python strategy/model_diff.py --old NOV.RAW --new DEC.RAW [--watch POTEETS,PEARSALL,TWINBU,HARGROVE]

Lists branches/transformers added, removed, or changed (reactance or rating),
keyed by (from bus, to bus, circuit) and labelled with ERCOT substation codes
via the Settlement_Points mapping. With --watch, prints every change touching
those stations: the direct test of when a known upgrade enters the auction
model (the "lag" question: Nodal Protocols 7.5.1(2) says upgrades enter for
auctions held AFTER the month they go in service).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pathlib

from strategy.grid_crosswalk import load_sp_map
from strategy.ptdf import parse_raw


def keyed(path):
    buses, branches = parse_raw(pathlib.Path(path))
    out = {}
    for b in branches:
        k = (min(b["i"], b["j"]), max(b["i"], b["j"]), str(b["ckt"]).strip(), b["kind"])
        out[k] = (round(b["x"], 6), round(b["rate"], 1))
    return buses, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--watch", default="")
    args = ap.parse_args()
    _st, bus_station = load_sp_map()
    ob, old = keyed(args.old)
    nb, new = keyed(args.new)
    name = lambda b, buses: bus_station.get(b) or (buses.get(b, {}).get("name", "?"))  # noqa: E731
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    print(f"buses old {len(ob)} new {len(nb)} (+{len(set(nb) - set(ob))} -{len(set(ob) - set(nb))}); "
          f"branches old {len(old)} new {len(new)}: added {len(added)}, removed {len(removed)}, changed {len(changed)}")
    watch = {w.strip().upper() for w in args.watch.split(",") if w.strip()}

    def label(k, buses):
        return f"{name(k[0], buses)}({k[0]}) - {name(k[1], buses)}({k[1]}) ckt {k[2]} {k[3]}"
    for title, keys, buses in (("ADDED", added, nb), ("REMOVED", removed, ob), ("CHANGED", changed, nb)):
        hits = [k for k in keys if not watch or {str(name(k[0], buses)).upper(), str(name(k[1], buses)).upper()} & watch]
        print(f"\n{title}: {len(keys)} total" + (f", {len(hits)} touching watched stations" if watch else ""))
        for k in (hits if watch else keys)[:40]:
            extra = f"  x/rate {old.get(k)} -> {new.get(k)}" if title == "CHANGED" else f"  x/rate {(new if title == 'ADDED' else old).get(k)}"
            print("  ", label(k, buses), extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
