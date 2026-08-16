"""Build public/grid_geo.json — the geographic layer for /map's Grid view.

No DB access: reuses public/node_graph.json for MW + link layers, plus the
archive's v3 node locations, station coordinates, and NRG-derived topology.
Rerun after build_node_graph.py:  python scripts/build_geo_layer.py
"""
import json
import os
import re

REF = os.path.expanduser("~/ercotcron-archive/ref")
PUB = os.path.join(os.path.dirname(__file__), "..", "public")

TX = dict(lat=(25.6, 36.6), lon=(-107.0, -93.4))
def in_tx(lat, lon):
    return TX["lat"][0] <= lat <= TX["lat"][1] and TX["lon"][0] <= lon <= TX["lon"][1]

graph = json.load(open(f"{PUB}/node_graph.json"))
v3 = json.load(open(f"{REF}/node_location_tiered_v3.json"))
stations = json.load(open(f"{REF}/station_coords.json"))
edges = json.load(open(f"{REF}/nrg_topology_edges.json"))["edges"]
exp = json.load(open(f"{REF}/constraint_exposure.json"))

# nodes: everything on the relationship map that has a location
mwmap = {}
def walk(n):
    if "children" in n:
        for c in n["children"]: walk(c)
    else:
        mwmap[n["name"]] = n.get("mw", 0)
walk(graph["tree"])

nodes = []
for name, mw in mwmap.items():
    r = v3.get(name) or {}
    lat, lon = r.get("lat"), r.get("lon")
    if lat and lon and in_tx(lat, lon):
        nodes.append({"name": name, "lat": round(lat, 4), "lon": round(lon, 4),
                      "mw": mw, "tier": r.get("tier", "D")})

# grid edges: both endpoints located, inside Texas
grid = []
for a, b in edges:
    ca, cb = stations.get(a), stations.get(b)
    if ca and cb and in_tx(*ca) and in_tx(*cb):
        grid.append([[round(ca[0], 4), round(ca[1], 4)], [round(cb[0], 4), round(cb[1], 4)]])

# CRR paths from the relationship layer, with coords
pos = {n["name"]: (n["lat"], n["lon"]) for n in nodes}
crr = []
for l in graph["links"]:
    if l["kind"] != "crr": continue
    a, b = pos.get(l["source"]), pos.get(l["target"])
    if a and b:
        crr.append({"a": a, "b": b, "v": l["value"],
                    "label": f'{l["source"]} → {l["target"]}'})

# constraints: decode station tokens out of constraint names, place at the
# midpoint of matched stations
def constraint_pos(cname):
    tokens = [t for t in re.split(r"[_\W]+", cname.upper()) if len(t) >= 4]
    hits = [stations[t] for t in tokens if t in stations]
    if not hits:
        hits = [stations[s] for s in stations
                if len(s) >= 5 and any(s in t or t in s for t in tokens)][:2]
    if not hits: return None
    lat = sum(h[0] for h in hits) / len(hits)
    lon = sum(h[1] for h in hits) / len(hits)
    return (round(lat, 4), round(lon, 4)) if in_tx(lat, lon) else None

cons = []
for cname in exp:
    p = constraint_pos(cname)
    if p:
        cons.append({"name": cname, "lat": p[0], "lon": p[1]})

out = {"nodes": nodes, "grid": grid, "crr": crr, "constraints": cons,
       "asOf": graph.get("asOf")}
json.dump(out, open(f"{PUB}/grid_geo.json", "w"))
print(f"grid_geo: {len(nodes)} nodes, {len(grid)} grid edges, "
      f"{len(crr)} crr paths, {len(cons)} constraints placed")
