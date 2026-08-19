"""One-time seed: move reference files and current generated outputs from the
local archive into the artifacts table, after which platform jobs own them.
This is deliberately the laptop's LAST required job."""
import json
import os

import psycopg

REF = os.path.expanduser("~/ercotcron-archive/ref")
PUB = os.path.join(os.path.dirname(__file__), "..", "public")

FILES = {
    # reference inputs the platform builders need
    "ref/constraint_exposure": f"{REF}/constraint_exposure.json",
    "ref/constraint_stability": f"{REF}/constraint_stability.json",
    "ref/node_geo": f"{REF}/node_geo.json",
    "ref/node_location_tiered_v3": f"{REF}/node_location_tiered_v3.json",
    "ref/station_coords": f"{REF}/station_coords.json",
    "ref/nrg_topology_edges": f"{REF}/nrg_topology_edges.json",
    # current outputs (jobs will overwrite these nightly)
    "node_graph": f"{PUB}/node_graph.json",
    "grid_geo": f"{PUB}/grid_geo.json",
    "strip_2028": f"{PUB}/strip_2028.json",
}

with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
    cur = c.cursor()
    for name, path in FILES.items():
        if not os.path.exists(path):
            print(f"skip {name}: {path} missing")
            continue
        body = json.load(open(path))
        cur.execute(
            """insert into artifacts (name, body, built_by) values (%s, %s, 'seed')
               on conflict (name) do update
                 set body = excluded.body, updated_at = now(), built_by = 'seed'""",
            (name, json.dumps(body)),
        )
        print(f"seeded {name} ({os.path.getsize(path)//1024} KB)")
    c.commit()
