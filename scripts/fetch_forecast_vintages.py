#!/usr/bin/env python3
"""Load ERCOT's archived load/wind/solar forecasts as they stood at the DAM deadline.

    python scripts/fetch_forecast_vintages.py --from 2024-10-01 --to 2026-10-14 [--products NP3-561-CD,NP4-742-CD,NP4-745-CD]

For each calendar day, take the edition posted at 09:30 Central (else the
latest posted between 08:00 and 09:59) and store every numeric column of it,
per delivery date, as an hour array in ercot_forecast_vintages. Days already
loaded for a product are skipped. Per-edition check: a complete edition has
>= 7 delivery dates with 23-25 hours each; otherwise it is reported and skipped.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import ROOT

load_dotenv(ROOT / ".env")
from ercot.client import ErcotClient

SKIP = {"deliverydate", "hourending", "dstflag"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    ap.add_argument("--products", default="NP3-561-CD,NP4-742-CD,NP4-745-CD")
    args = ap.parse_args()
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)
    client = ErcotClient()

    def get(url, tries=5):
        for a in range(tries):
            try:
                h = {"Authorization": f"Bearer {client.token()}",
                     "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=300) as r:
                    return r.read()
            except Exception:
                if a == tries - 1:
                    raise
                time.sleep(8 * (a + 1))

    for prod in args.products.split(","):
        with psycopg.connect(os.environ["DATABASE_URL"]) as c:
            have = {r[0] for r in c.execute("select distinct posted_at::date from ercot_forecast_vintages where product=%s", (prod,))}
        bad, done = [], 0
        day = d0
        while day <= d1:
            if day in have:
                day += timedelta(days=1)
                continue
            lst = json.loads(get(f"https://api.ercot.com/api/public-reports/archive/{prod}?size=100"
                                 f"&postDatetimeFrom={day}T08:00:00&postDatetimeTo={day}T09:59:59"))
            arcs = sorted(lst.get("archives") or [], key=lambda a: a["postDatetime"])
            pick = next((a for a in arcs if a["postDatetime"][11:16] == "09:30"), arcs[-1] if arcs else None)
            if not pick:
                bad.append(f"{day}: no edition 08:00-09:59")
                day += timedelta(days=1)
                continue
            z = zipfile.ZipFile(io.BytesIO(get(pick["_links"]["endpoint"]["href"])))
            r = csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"))
            hdr = next(r)
            low = [x.strip().lower().replace("_", "") for x in hdr]
            di, hi = low.index("deliverydate"), low.index("hourending")
            fi = low.index("dstflag") if "dstflag" in low else None
            series = [i for i, x in enumerate(low) if x not in SKIP]
            cells = defaultdict(dict)  # (date, col) -> {(he, dst): v}
            slots = defaultdict(set)
            for row in r:
                dd = datetime.strptime(row[di], "%m/%d/%Y").date()
                s = (int(row[hi].split(":")[0]), fi is not None and row[fi].upper() == "Y")
                slots[dd].add(s)
                for i in series:
                    try:
                        cells[(dd, hdr[i].strip())][s] = float(row[i]) if row[i] not in ("", None) else None
                    except ValueError:
                        pass
            ok_days = [dd for dd, ss in slots.items() if 23 <= len(ss) <= 25]
            if len(ok_days) < 7:
                bad.append(f"{day}: only {len(ok_days)} complete delivery days")
                day += timedelta(days=1)
                continue
            posted = datetime.fromisoformat(pick["postDatetime"][:19])
            rows = [(prod, posted, dd, col, [vals.get(s) for s in sorted(slots[dd])])
                    for (dd, col), vals in cells.items() if dd in ok_days]
            with psycopg.connect(os.environ["DATABASE_URL"]) as c:
                with c.cursor() as cur, cur.copy("copy ercot_forecast_vintages from stdin") as cp:
                    for row in rows:
                        cp.write_row(row)
                c.commit()
            done += 1
            if done % 25 == 0:
                print(f"{prod}: {done} editions loaded (through {day}, posted {posted})", flush=True)
            day += timedelta(days=1)
        print(f"{prod}: done, {done} editions; problems: {bad or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
