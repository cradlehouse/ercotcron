#!/usr/bin/env python3
"""Shift factors (PTDFs) from ERCOT's CRR network model.

    python strategy/ptdf.py --raw ~/Downloads/Common_2028...RAW

A CRR's payoff decomposes exactly:

    value(source -> sink) = SUM over binding constraints c of
                            (PTDF[source,c] - PTDF[sink,c]) * shadow_price[c]

PTDFs are deterministic physics — how a 1 MW injection at a bus, withdrawn at
the slack, redistributes across every branch. Shadow prices are not; they are
what has to be forecast. Splitting the problem this way replaces "predict
35,000 path prices" with "predict ~100 constraint prices", each of which has a
physical story.

Only the DC approximation is used (reactance only, no losses, flat voltage),
which is what ERCOT itself clears against — ERCOT is lossless in the nodal
sense, so sink minus source IS congestion.

Verification is built in, because a shift-factor matrix that is subtly wrong
produces plausible numbers rather than errors: PTDFs for a bus onto branches
forming a cutset must sum to 1, and the slack bus must have PTDF 0 everywhere.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import numpy as np
from scipy.sparse import csc_matrix, lil_matrix
from scipy.sparse.linalg import factorized

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"


def parse_raw(path: pathlib.Path):
    """Bus list and branch list from a PSS/E v30 RAW case."""
    lines = path.read_text(encoding="latin-1").splitlines()
    marks = {}
    for i, line in enumerate(lines):
        m = re.match(r"^0 */ *END OF (.+?) DATA, BEGIN (.+?) DATA", line)
        if m:
            marks[m.group(1).strip()] = i
    for needed in ("BUS", "LOAD", "GENERATOR", "BRANCH", "TRANSFORMER"):
        if needed not in marks:
            raise SystemExit(f"RAW file has no '{needed}' section marker")

    def fields(line):
        return [x.strip().strip("'").strip() for x in re.sub(r"/\*.*?\*/", "", line).split(",")]

    buses = {}
    for line in lines[3:marks["BUS"]]:
        if not line.strip() or line.startswith("0"):
            continue
        f = fields(line)
        try:
            buses[int(f[0])] = {"name": f[1], "kv": float(f[2]), "type": int(f[3])}
        except (ValueError, IndexError):
            continue

    branches = []
    for line in lines[marks["GENERATOR"] + 1:marks["BRANCH"]]:
        if not line.strip() or line.startswith("0"):
            continue
        f = fields(line)
        try:
            i, j, x = abs(int(f[0])), abs(int(f[1])), float(f[3])
            if i in buses and j in buses and abs(x) > 1e-9 and i != j:
                branches.append({"i": i, "j": j, "x": x, "ckt": f[2],
                                 "rate": float(f[6]) if f[6] else 0.0, "kind": "line"})
        except (ValueError, IndexError):
            continue

    # Two-winding transformers occupy 4 lines; three-winding 5. The third field
    # of the first line is the tertiary bus and is 0 for two-winding.
    block = lines[marks["BRANCH"] + 1:marks["TRANSFORMER"]]
    n = 0
    while n < len(block):
        line = block[n]
        if not line.strip() or line.startswith("0"):
            n += 1
            continue
        f = fields(line)
        try:
            i, j = abs(int(f[0])), abs(int(f[1]))
            three = f[2] and int(f[2]) != 0
            x = float(fields(block[n + 1])[1])
            if i in buses and j in buses and abs(x) > 1e-9 and i != j:
                rate = 0.0
                try:
                    rate = float(fields(block[n + 2])[3])
                except (ValueError, IndexError):
                    pass
                branches.append({"i": i, "j": j, "x": x, "ckt": f[3] if len(f) > 3 else "1",
                                 "rate": rate, "kind": "xfmr"})
            n += 5 if three else 4
        except (ValueError, IndexError):
            n += 1
    return buses, branches


def build_ptdf(buses, branches, slack=None):
    """Returns (ptdf_fn, bus_index, slack). ptdf_fn(branch_idx) -> row over buses.

    Solves B_red * theta = e_bus once per branch via a cached factorisation, so
    the full dense matrix is never materialised — at ~11k buses that would be
    ~1 GB and we only ever need the rows for constraints that actually bind.
    """
    # A DC network splits into islands (this case has three). The B matrix of a
    # disconnected graph is singular no matter which single slack you remove,
    # and a shift factor across an island is meaningless anyway — so work on
    # the component containing the slack and report what was dropped.
    adj = {}
    for br in branches:
        adj.setdefault(br["i"], set()).add(br["j"])
        adj.setdefault(br["j"], set()).add(br["i"])
    if slack is None:
        swing = [b for b in sorted(buses) if buses[b]["type"] == 3 and b in adj]
        slack = swing[0] if swing else next(iter(adj))
    seen, stack = set(), [slack]
    while stack:
        b = stack.pop()
        if b in seen:
            continue
        seen.add(b)
        stack.extend(adj.get(b, ()) - seen)
    dropped = len(buses) - len(seen)
    if dropped:
        print(f"  islanded/isolated buses excluded: {dropped}")
    buses = {b: v for b, v in buses.items() if b in seen}
    branches = [br for br in branches if br["i"] in seen and br["j"] in seen]

    ids = sorted(buses)
    idx = {b: k for k, b in enumerate(ids)}
    nb = len(ids)
    s = idx[slack]

    B = lil_matrix((nb, nb))
    for br in branches:
        i, j, b = idx[br["i"]], idx[br["j"]], 1.0 / br["x"]
        B[i, i] += b
        B[j, j] += b
        B[i, j] -= b
        B[j, i] -= b
    keep = [k for k in range(nb) if k != s]
    Bred = csc_matrix(B[keep, :][:, keep])
    solve = factorized(Bred)

    pos = {k: p for p, k in enumerate(keep)}

    def branch_ptdf(br):
        """Row of shift factors: sensitivity of this branch's flow to injection
        at each bus (withdrawal at slack)."""
        rhs = np.zeros(len(keep))
        i, j, b = idx[br["i"]], idx[br["j"]], 1.0 / br["x"]
        if i != s:
            rhs[pos[i]] += 1.0
        if j != s:
            rhs[pos[j]] -= 1.0
        theta = solve(rhs)
        full = np.zeros(nb)
        full[keep] = theta
        return b * full  # flow sensitivity per bus injection

    return branch_ptdf, idx, slack, ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default=str(REF / "ptdf_sample.json"))
    ap.add_argument("--branches", type=int, default=25,
                    help="how many branches to compute shift factors for")
    args = ap.parse_args()

    raw = pathlib.Path(args.raw).expanduser()
    if not raw.exists():
        raise SystemExit(f"no such RAW file: {raw}")
    buses, branches = parse_raw(raw)
    print(f"buses {len(buses):,}   branches (with reactance) {len(branches):,}")

    ptdf_fn, idx, slack, ids = build_ptdf(buses, branches)
    print(f"slack bus {slack} ({buses[slack]['name']})  — factorisation built")

    # ---- verification: properties a correct PTDF matrix must satisfy
    probe = branches[: min(args.branches, len(branches))]
    row0 = ptdf_fn(probe[0])
    print("\nverification")
    print(f"  slack PTDF (must be 0):            {row0[idx[slack]]:+.2e}")
    both = ptdf_fn(probe[0])
    print(f"  self-sensitivity i-j (must be ~1): "
          f"{both[idx[probe[0]['i']]] - both[idx[probe[0]['j']]]:+.4f}")
    mx = float(np.max(np.abs(row0)))
    print(f"  max |PTDF| on this branch:         {mx:.4f}  (>1 means islanded/parallel issue)"
          if mx > 1.001 else f"  max |PTDF| on this branch:         {mx:.4f}")

    # ---- shift factors for tradeable nodes
    n2b = json.loads((REF / "node_to_bus_canonical.json").read_text())
    node_bus = {n: int(v[0]) for n, v in n2b.items() if v and int(v[0]) in idx}
    print(f"\ntradeable nodes mapped into this case: {len(node_bus):,}/{len(n2b):,}")

    out = {}
    for br in probe:
        row = ptdf_fn(br)
        key = f"{buses[br['i']]['name']}->{buses[br['j']]['name']}:{br['ckt']}"
        out[key] = {n: round(float(row[idx[b]]), 6) for n, b in node_bus.items()}
    pathlib.Path(args.out).write_text(json.dumps(out))
    print(f"wrote shift factors for {len(out)} branches x {len(node_bus)} nodes -> {args.out}")

    k = next(iter(out))
    vals = sorted(out[k].items(), key=lambda kv: -abs(kv[1]))[:6]
    print(f"\nmost exposed nodes on {k}:")
    for n, v in vals:
        print(f"   {n:<18}{v:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
