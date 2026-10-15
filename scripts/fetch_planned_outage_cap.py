#!/usr/bin/env python3
"""Load ERCOT's archived planned outage capacity editions (NP3-161-CD).

    python scripts/fetch_planned_outage_cap.py --from 2024-10-01 --to 2026-10-14

"Available Resource Planned Outage Capacity Margin, 7 Day Plus": system-wide MW
of resources scheduled out, per operating day, from about 7 days ahead to
about 5 years ahead (thermal non-IRR, IRR, ESR; approved vs received). One
edition per day (the latest posted that calendar day) goes into
ercot_forecast_vintages with product 'NP3-161-CD', ONE ROW PER (edition,
column): delivery_date is the FIRST operating date in the edition and vals is
the DAILY series from that date onward (unlike the hourly products). Every
edition is kept, so a test can use the outage plan as it stood on any auction
date. Skips editions already loaded; a non-contiguous date run is reported and
skipped.
"""
from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import os
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import ROOT

load_dotenv(ROOT / ".env")
from ercot.client import ErcotClient

PROD = "NP3-161-CD"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    args = ap.parse_args()
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)
    client = ErcotClient()

    def get(url, tries=8):
        for a in range(tries):
            try:
                h = {"Authorization": f"Bearer {client.token()}",
                     "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=300) as r:
                    return r.read()
            except Exception as e:
                if a == tries - 1:
                    raise
                if getattr(e, "code", None) == 429:  # rate limited: back off hard
                    time.sleep(60 * (a + 1))
                    continue
                time.sleep(8 * (a + 1))

    docs, page = [], 1
    while True:
        d = json.loads(get(f"https://api.ercot.com/api/public-reports/archive/{PROD}?size=1000&page={page}"
                           f"&postDatetimeFrom={d0}T00:00:00&postDatetimeTo={d1}T23:59:59"))
        docs += d.get("archives") or []
        if page >= ((d.get("_meta") or {}).get("totalPages") or page):
            break
        page += 1
    latest = {}
    for a in docs:  # one edition per posting day: the latest that day
        k = a["postDatetime"][:10]
        if k not in latest or a["postDatetime"] > latest[k]["postDatetime"]:
            latest[k] = a
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        have = {r[0] for r in c.execute("select distinct posted_at::date from ercot_forecast_vintages where product=%s", (PROD,))}
    bad, done = [], 0
    for k in sorted(latest):
        a = latest[k]
        if date.fromisoformat(k) in have:
            continue
        z = zipfile.ZipFile(io.BytesIO(get(a["_links"]["endpoint"]["href"])))
        rows = list(csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1")))
        dates = [datetime.strptime(r["OperatingDate"], "%m/%d/%Y").date() for r in rows]
        if not dates or any((b - a2).days != 1 for a2, b in itertools.pairwise(dates)):
            bad.append(k)
            continue
        posted = datetime.fromisoformat(a["postDatetime"][:19])
        out = []
        for col in rows[0]:
            if col == "OperatingDate":
                continue
            vals = []
            for r in rows:
                try:
                    vals.append(float(r[col]))
                except (TypeError, ValueError):
                    vals.append(None)
            out.append((PROD, posted, dates[0], col, vals))
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            with c.cursor() as cur, cur.copy("copy ercot_forecast_vintages from stdin") as cp:
                for row in out:
                    cp.write_row(row)
            c.commit()
        done += 1
        if done % 50 == 0:
            print(f"{done} editions (through {k})", flush=True)
    print(f"done: {done} editions loaded; non-contiguous/skipped: {bad or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
