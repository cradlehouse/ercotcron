"""Build public/node_graph.json for the /map page.

Tree:  ERCOT -> load zone -> substation -> settlement point
       node value = live CRR MW touching the point (mw), avg |hourly basis| (dart)
Links: crr        = top live awarded paths by MW
       congestion = each major constraint's cheap-side -> expensive-side nodes
                    (from the empirical exposure map)
       shareddrv  = point pairs whose value loads on the same driving constraint
All inputs public; regenerate any time:  python scripts/build_node_graph.py
"""
import json
import os
import collections

import psycopg

REF = os.path.expanduser("~/ercotcron-archive/ref")
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "node_graph.json")
TOP_POINTS = 120
TOP_PATHS = 40
TOP_CONSTRAINTS = 25

geo = json.load(open(f"{REF}/node_geo.json"))

with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
    c.execute("set statement_timeout=0")
    cur = c.cursor()
    # live MW per settlement point (either side of a live position)
    cur.execute("""
        with live as (select source, sink, mw from crr_awards where end_date >= now()::date)
        select p, sum(mw) from (
          select source p, mw from live union all select sink p, mw from live
        ) x group by 1 order by 2 desc limit %s""", (TOP_POINTS,))
    mw = {r[0]: float(r[1]) for r in cur.fetchall()}

    # pull constraint-sensitive nodes into the map even when their MW rank is
    # lower — the red/indigo layers live on these
    exp_nodes = list({e["node"] for v in json.load(open(f"{REF}/constraint_exposure.json")).values()
                      for e in v if abs(e.get("beta", 0)) >= 0.03} - set(mw))
    if exp_nodes:
        cur.execute("""
            with live as (select source, sink, mw from crr_awards where end_date >= now()::date)
            select p, sum(mw) from (
              select source p, mw from live union all select sink p, mw from live
            ) x where p = any(%s) group by 1 order by 2 desc limit 60""", (exp_nodes,))
        for r in cur.fetchall():
            mw[r[0]] = float(r[1])

    cur.execute("""select settlement_point, avg(abs(basis)) from node_hourly_basis
                    where settlement_point = any(%s) group by 1""", (list(mw),))
    dart = {r[0]: round(float(r[1]), 2) for r in cur.fetchall()}

    cur.execute("""select source, sink, sum(mw) from crr_awards
                    where end_date >= now()::date and source = any(%s) and sink = any(%s)
                    group by 1, 2 order by 3 desc limit %s""",
                (list(mw), list(mw), TOP_PATHS))
    crr_links = [{"source": s, "target": t, "kind": "crr",
                  "value": round(float(v) ** 0.5 / 3, 1)} for s, t, v in cur.fetchall()]

# congestion + shared-driver links from the exposure map
exp = json.load(open(f"{REF}/constraint_exposure.json"))
stab = {}
try:
    stab = {k: v.get("binding_hours", 0) for k, v in
            json.load(open(f"{REF}/constraint_stability.json")).items()}
except Exception:
    pass

# rank constraints by how many of their material nodes made it onto the map
def in_map(entries):
    return [e for e in entries if e["node"] in mw and abs(e["beta"]) >= 0.02]

ranked = sorted(exp.items(), key=lambda kv: (-len(in_map(kv[1])),
                                             -stab.get(kv[0], 0)))[:TOP_CONSTRAINTS]
cong_links, shared_links, seen_pairs = [], [], set()
for cname, entries in ranked:
    inside = in_map(entries)
    if len(inside) < 2:
        continue
    pos = sorted((e for e in inside if e["beta"] > 0), key=lambda e: -e["beta"])
    neg = sorted((e for e in inside if e["beta"] < 0), key=lambda e: e["beta"])
    if pos and neg:   # cheap side -> expensive side
        pair = (neg[0]["node"], pos[0]["node"])
        if pair not in seen_pairs and pair[0] != pair[1]:
            seen_pairs.add(pair)
            cong_links.append({"source": pair[0], "target": pair[1], "kind": "congestion",
                               "value": round(min(9, 2 + abs(pos[0]["beta"]) * 40), 1),
                               "label": cname})
    # same-side pairs share the driver
    side = pos if len(pos) >= 2 else neg
    for a, b in zip(side, side[1:3]):
        pair = tuple(sorted((a["node"], b["node"])))
        if pair[0] != pair[1] and pair not in seen_pairs:
            seen_pairs.add(pair)
            shared_links.append({"source": pair[0], "target": pair[1],
                                 "kind": "shareddrv", "value": 2, "label": cname})

# hierarchy: zone -> substation -> point
zones = collections.defaultdict(lambda: collections.defaultdict(list))
for p, v in mw.items():
    g = geo.get(p, {})
    zone = (g.get("zone") or "OTHER").replace("LZ_", "")
    sub = g.get("substation") or p.split("_")[0]
    zones[zone][sub].append({"name": p, "mw": round(v), "dart": dart.get(p, 0)})

tree = {"name": "ERCOT", "children": [
    {"name": z, "children": [
        {"name": s, "children": pts} for s, pts in sorted(subs.items())
    ]} for z, subs in sorted(zones.items())
]}

out = {"tree": tree, "links": crr_links + cong_links + shared_links,
       "asOf": __import__("datetime").date.today().isoformat(),
       "points": len(mw)}
json.dump(out, open(OUT, "w"))
print(f"wrote {OUT}: {len(mw)} points, {len(crr_links)} crr / "
      f"{len(cong_links)} congestion / {len(shared_links)} shared-driver links")
