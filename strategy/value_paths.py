#!/usr/bin/env python3
"""Physical path valuation: shift factors x expected shadow prices.

    python strategy/value_paths.py --raw ~/Downloads/Common_2028...RAW --top 60

The congestion component of a nodal price is, exactly:

    congestion_i = - SUM over binding constraints c of  PTDF[i,c] * mu_c

so the value of a source->sink path is

    value = congestion_sink - congestion_source
          = SUM over c of  (PTDF[source,c] - PTDF[sink,c]) * mu_c

PTDFs are physics and come from the network model. mu_c — how often each
constraint binds and how hard — comes from a year of 5-minute SCED history.
That split is the point: every statistical approach tried on this project
assumed last month's PATH prices repeat, and January 2026 punished it. Here the
only thing assumed to persist is which CONSTRAINTS bind, which is a far smaller
and more physical claim (756 constraints, and the top ten carry ~47% of rent).

Validation is the whole script, not an afterthought. Model values are scored
against realised day-ahead congestion on the same paths. A model that cannot
beat "predict zero" is reported as such.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import pathlib
import re
import statistics
import sys

import numpy as np
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "strategy"))

import psycopg  # noqa: E402
from ptdf import build_ptdf, parse_raw  # noqa: E402

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"
CACHE = pathlib.Path.home() / "ercotcron-archive" / "cache"


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def load_constraints(min_intervals=200):
    """Per constraint: expected shadow price contribution and its stations.

    Expected contribution is mean shadow price x share of intervals binding —
    i.e. the unconditional expectation, which is what a month-ahead position
    is exposed to, not the conditional-on-binding price.
    """
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as c:
        cur = c.cursor()
        cur.execute("select count(distinct sced_timestamp) from binding_constraints")
        total_intervals = cur.fetchone()[0]
        cur.execute("""
            select constraint_name,
                   max(from_station), max(to_station),
                   count(*)                       as n,
                   avg(shadow_price)              as avg_sp
              from binding_constraints
             where shadow_price is not null and from_station is not null
               and from_station <> 'n/a'
             group by 1
            having count(*) >= %s
             order by sum(shadow_price) desc
        """, (min_intervals,))
        rows = cur.fetchall()
    out = []
    for name, fs, ts, n, avg_sp in rows:
        out.append({"name": name, "from": fs, "to": ts, "n": n,
                    "avg_sp": float(avg_sp or 0),
                    "expected": float(avg_sp or 0) * n / max(total_intervals, 1)})
    return out, total_intervals


def match_branch(con, buses, branches):
    """Find the network branch a constraint refers to, via its two stations."""
    byname = collections.defaultdict(list)
    for b, v in buses.items():
        byname[norm(v["name"])].append(b)

    def candidates(station):
        n = norm(station)
        if n in byname:
            return byname[n]
        hits = [b for nm, bl in byname.items()
                if len(n) >= 4 and (nm.startswith(n) or re.sub(r"\d+[A-Z]?$", "", nm) == n)
                for b in bl]
        return hits

    f_c, t_c = candidates(con["from"]), candidates(con["to"])
    if not f_c or not t_c:
        return None
    fs, ts = set(f_c), set(t_c)
    for i, br in enumerate(branches):
        # The RAW file's i->j ordering is arbitrary; ERCOT's from->to is the
        # monitored direction. Return which way round it is, because getting
        # this wrong flips the shift factor's sign and inverts the valuation.
        if br["i"] in fs and br["j"] in ts:
            return i, +1.0
        if br["j"] in fs and br["i"] in ts:
            return i, -1.0
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--top", type=int, default=60, help="constraints to model")
    ap.add_argument("--month", default="nov25", help="cached DAM month for validation")
    args = ap.parse_args()

    buses, branches = parse_raw(pathlib.Path(args.raw).expanduser())
    print(f"network: {len(buses):,} buses, {len(branches):,} branches")

    cons, total_int = load_constraints()
    print(f"constraints with history: {len(cons):,} (over {total_int:,} SCED intervals)")

    ptdf_fn, idx, slack, ids = build_ptdf(buses, branches)
    print(f"slack {slack} ({buses[slack]['name']})")

    # build_ptdf drops islanded buses, so a branch can match a constraint yet
    # reference a bus the factorisation never saw. Filter on idx membership.
    modelled, unmatched, offgrid = [], [], []
    for con in cons:
        hit = match_branch(con, buses, branches)
        if hit is None:
            unmatched.append(con)
            continue
        bi, orient = hit
        br = branches[bi]
        if br["i"] not in idx or br["j"] not in idx:
            offgrid.append(con)
            continue
        modelled.append((con, bi, orient))
        if len(modelled) >= args.top:
            break
    print(f"constraints mapped onto a branch: {len(modelled)}  "
          f"(no station match: {len(unmatched)}, on islanded buses: {len(offgrid)})")
    if not modelled:
        print("no constraint could be located on the network — cannot value")
        return 1
    flipped = sum(1 for _, _, o in modelled if o < 0)
    print(f"expected shadow-price mass modelled: "
          f"${sum(c['expected'] for c, _, _ in modelled):,.2f}/MWh-equivalent")
    print(f"branch orientation opposite to ERCOT from->to: {flipped}/{len(modelled)}")

    n2b = json.loads((REF / "node_to_bus_canonical.json").read_text())
    node_bus = {n: int(v[0]) for n, v in n2b.items() if v and int(v[0]) in idx}
    print(f"tradeable nodes on this network: {len(node_bus):,}")

    # congestion_i = - sum_c PTDF[i,c] * mu_c
    cong = collections.defaultdict(float)
    for con, bi, orient in modelled:
        row = ptdf_fn(branches[bi]) * orient
        mu = con["expected"]
        for node, b in node_bus.items():
            cong[node] -= row[idx[b]] * mu
    out = {n: round(v, 6) for n, v in cong.items()}
    (REF / "node_congestion_model.json").write_text(json.dumps(out))
    print(f"wrote modelled congestion for {len(out):,} nodes")

    top = sorted(out.items(), key=lambda kv: kv[1])
    print("\nmost NEGATIVE modelled congestion (cheap nodes — good CRR sources):")
    for n, v in top[:6]:
        print(f"   {n:<18}{v:+.4f}")
    print("most POSITIVE (expensive nodes — good CRR sinks):")
    for n, v in top[-6:]:
        print(f"   {n:<18}{v:+.4f}")

    # ---- validation against realised day-ahead congestion
    dam = None
    for d in (CACHE, pathlib.Path("/tmp")):
        p = d / f"dam_{args.month}.json"
        if p.exists():
            dam = json.loads(p.read_text())
            break
    if dam is None:
        print(f"\nno cached DAM for {args.month} — skipping validation")
        return 0

    P = collections.defaultdict(dict)
    for r in dam:
        P[(r["delivery_date"], r["hour_ending"])][r["settlement_point"]] = float(r["price"])
    acc = collections.defaultdict(list)
    for pr in P.values():
        vals = list(pr.values())
        if len(vals) < 100:
            continue
        sysmean = statistics.fmean(vals)
        for node, price in pr.items():
            if node in out:
                acc[node].append(price - sysmean)
    real = {n: statistics.fmean(v) for n, v in acc.items() if len(v) > 100}
    common = sorted(set(real) & set(out))
    print(f"\nVALIDATION on {args.month}: {len(common):,} nodes with both model and actual")
    if len(common) < 30:
        print("too few overlapping nodes to score")
        return 0
    xs = [out[n] for n in common]
    ys = [real[n] for n in common]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    r = (sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (len(xs) * sx * sy)) if sx and sy else 0.0
    t = r * math.sqrt((len(xs) - 2) / max(1e-12, 1 - r * r))
    print(f"  corr(model, realised nodal basis) = {r:+.3f}   t={t:+.1f}   n={len(common):,}")
    q = len(common) // 5
    order = sorted(common, key=lambda n: out[n])
    print(f"\n  {'model quintile':<16}{'mean model':>12}{'mean actual':>13}{'nodes':>7}")
    for i in range(5):
        ch = order[i * q:(i + 1) * q] if i < 4 else order[4 * q:]
        print(f"  Q{i+1:<15}{statistics.fmean(out[n] for n in ch):>+12.4f}"
              f"{statistics.fmean(real[n] for n in ch):>+13.3f}{len(ch):>7}")
    print("\n  A monotone actual column means the physics ranks nodes correctly even")
    print("  where the magnitude is off. Flat or inverted means it does not work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
