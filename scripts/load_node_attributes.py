#!/usr/bin/env python3
"""Load derived node reference data into Supabase.

    python scripts/load_node_attributes.py

Applies supabase/migrations/20260729130000_node_attributes.sql if the tables do
not exist yet, then loads from ~/ercotcron-archive/ref/. Idempotent: re-running
replaces rows rather than duplicating them.

Reads DATABASE_URL from .env. That must be the session-mode pooler (port 5432),
not the transaction pooler (6543) — the latter refuses DDL.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")

import psycopg  # noqa: E402

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"
MIGRATION = (pathlib.Path(__file__).resolve().parents[1]
             / "supabase" / "migrations" / "20260729130000_node_attributes.sql")


def load_json(name: str) -> dict:
    path = REF / name
    if not path.exists():
        print(f"  missing {name} — skipping the fields it supplies")
        return {}
    return json.loads(path.read_text())


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn or "YOUR-PASSWORD" in dsn or "REGION" in dsn:
        print("DATABASE_URL is unset or still a placeholder. Add the real "
              "session-pooler string (port 5432) to .env first.")
        return 1

    tiered = load_json("node_location_tiered.json")
    tech = load_json("node_tech_class.json")
    bus = load_json("node_to_bus_canonical.json")
    cty_ercot = load_json("node_county_canonical.json")
    cty_gis = load_json("node_county_gis.json")
    geo = load_json("node_geo.json")

    names = set(geo) | set(tiered) | set(tech)
    if not names:
        print("no reference data found in", REF)
        return 1

    rows = []
    for n in sorted(names):
        t = tiered.get(n) or {}
        rows.append((
            n,
            (bus.get(n) or [None])[0],
            t.get("load_zone") or (geo.get(n) or {}).get("zone"),
            t.get("substation") or (geo.get(n) or {}).get("substation"),
            cty_ercot.get(n),
            cty_gis.get(n),
            (tech.get(n) or {}).get("class"),
            (tech.get(n) or {}).get("gis_mw"),
            t.get("lat"),
            t.get("lon"),
            t.get("tier"),
            t.get("loc_source"),
        ))

    events = []
    ev_path = pathlib.Path("/tmp/energizations.json")
    if not ev_path.exists():
        ev_path = pathlib.Path.home() / "ercotcron-archive" / "cache" / "energizations.json"
    if ev_path.exists():
        for e in json.loads(ev_path.read_text()):
            for sp in e.get("nodes", []):
                events.append((sp, e.get("name"), e.get("fuel"), e.get("mw"),
                               e.get("county"), e.get("cod"), e.get("poi")))

    with psycopg.connect(dsn, connect_timeout=30) as conn:
        conn.execute("set statement_timeout = '10min'")
        with conn.cursor() as cur:
            cur.execute("select to_regclass('public.node_attributes')")
            if cur.fetchone()[0] is None:
                print("applying migration…")
                cur.execute(MIGRATION.read_text())
                conn.commit()

            cur.executemany(
                """insert into node_attributes
                   (settlement_point, psse_bus, load_zone, substation,
                    county_ercot, county_gis, tech_class, gis_mw,
                    latitude, longitude, location_tier, location_source)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (settlement_point) do update set
                     psse_bus=excluded.psse_bus, load_zone=excluded.load_zone,
                     substation=excluded.substation, county_ercot=excluded.county_ercot,
                     county_gis=excluded.county_gis, tech_class=excluded.tech_class,
                     gis_mw=excluded.gis_mw, latitude=excluded.latitude,
                     longitude=excluded.longitude, location_tier=excluded.location_tier,
                     location_source=excluded.location_source, updated_at=now()""",
                rows)
            print(f"node_attributes: {len(rows):,} rows upserted")

            if events:
                cur.execute("truncate node_energizations")
                cur.executemany(
                    """insert into node_energizations
                       (settlement_point, project_name, fuel, capacity_mw,
                        county, cod, poi_location)
                       values (%s,%s,%s,%s,%s,%s,%s)""",
                    events)
                print(f"node_energizations: {len(events):,} rows loaded")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("""select location_tier, count(*) from node_attributes
                           group by 1 order by 1""")
            print("\nby location tier:", dict(cur.fetchall()))
            cur.execute("""select tech_class, count(*) from node_attributes
                           where tech_class is not null group by 1 order by 2 desc""")
            print("by tech class:", dict(cur.fetchall()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
