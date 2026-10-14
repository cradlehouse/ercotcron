#!/usr/bin/env python3
"""Data coverage manifest (replay-plan addendum, 'data coverage gate').

    python strategy/data_manifest.py [--out REF/data_manifest_<date>.json]

For each source table: first/last date, distinct days present, and days missing
inside that span. A first-pass manifest: it records coverage, not forecast
publication times. Those are listed per source as known/unknown. Read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import REF, ROOT

load_dotenv(ROOT / ".env")

# table, date expression, kind, availability-time evidence
SOURCES = [
    ("dam_spp", "delivery_date", "actual (DAM settlement prices)", "posted day before delivery; posted_at null"),
    ("dam_constraints", "delivery_date", "actual (DAM binding constraints)", "posted day before delivery"),
    ("binding_constraints", "sced_timestamp::date", "actual (real-time SCED constraints)", "near real time"),
    ("node_day_spread", "delivery_date", "derived from dam_spp", "derived"),
    ("resource_outages", "report_date", "snapshot reports of unit outages (planned + forced)", "report_date = posting"),
    ("wind_power", "delivery_date", "actual + ERCOT forecast (latest vintage only)", "forecast vintage NOT preserved"),
    ("load_forecast", "delivery_date", "ERCOT forecast (latest vintage only)", "posted_at stored"),
    ("net_load", "delivery_date", "actual", "near real time"),
    ("weather_forecast", "interval_start::date", "Open-Meteo forecast (overwritten)", "not preserved"),
    ("weather_forecast_vintages", "first_seen_at::date", "Open-Meteo forecast vintages (append-only)", "first_seen_at; ref_run_init"),
    ("crr_awards", "start_date", "auction results", "per auction results date"),
    ("crr_point_prices", "null", "auction nodal clearing prices", "per auction results date"),
    ("transmission_projects", "report_date", "TPIT releases", "release date"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REF / f"data_manifest_{date.today()}.json"))
    args = ap.parse_args()
    out = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='170s'")
        for table, expr, kind, avail in SOURCES:
            if expr == "null":
                n = c.execute(f"select count(distinct auction_name) from {table}").fetchone()[0]
                out[table] = dict(kind=kind, availability=avail, auctions=n)
            else:
                lo, hi, days = c.execute(f"select min({expr}), max({expr}), count(distinct {expr}) from {table}").fetchone()
                span = (hi - lo).days + 1 if lo and hi else 0
                out[table] = dict(kind=kind, availability=avail, first=str(lo), last=str(hi),
                                  days_present=days, days_missing_in_span=span - days)
            print(f"{table:28} {json.dumps(out[table])}")
    out["_files"] = {p.name: p.stat().st_size for p in REF.glob("*.RAW")} | {
        "network_models_in_Downloads": sorted(x.name for x in (ROOT.parent / "Downloads").glob("*NetworkModel*.RAW"))
        if (ROOT.parent / "Downloads").exists() else []}
    json.dump(out, open(args.out, "w"), indent=1, default=str)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
