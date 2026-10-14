#!/usr/bin/env python3
"""Fetch ERCOT 60-Day SCED Disclosure (NP3-965-ER) and keep hourly unit output.

    python scripts/fetch_sced60.py --from 2024-10-01 --to 2026-08-31

One public zip per operating day (~48 MB, posted 60 days after the day). From
Gen_Resource_Data and ESR_Data we keep, per resource per hour ending:
mean Telemetered Net Output (delivered), mean Base Point (dispatched), and
mean HSL (available). Resource names are UNIT_SUBSTATION_UNIT, which map to
substations and PSS/E buses via ERCOT's Settlement_Points/Resource_Node_to_Unit
files. Output: CACHE/sced60/<operating day>.csv.gz (local research data, not
the database). Skips days already written, so it resumes.
"""
from __future__ import annotations

import argparse
import csv
import gzip
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
from dotenv import load_dotenv

from strategy.common import CACHE, ROOT

load_dotenv(ROOT / ".env")
from ercot.client import ErcotClient

API = "https://api.ercot.com/api/public-reports/archive/NP3-965-ER"
KEEP = ("Gen_Resource_Data", "ESR_Data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    args = ap.parse_args()
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)
    out = CACHE / "sced60"
    out.mkdir(parents=True, exist_ok=True)
    client = ErcotClient()

    def get(url, tries=5):
        for a in range(tries):
            try:
                h = {"Authorization": f"Bearer {client.token()}",
                     "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=600) as r:
                    return r.read()
            except Exception:
                if a == tries - 1:
                    raise
                time.sleep(10 * (a + 1))

    # list archives posted in the window that covers the operating days (+60d)
    p0, p1 = d0 + timedelta(days=55), d1 + timedelta(days=66)
    docs, page = [], 1
    while True:
        d = json.loads(get(f"{API}?size=1000&page={page}&postDatetimeFrom={p0}T00:00:00&postDatetimeTo={p1}T23:59:59"))
        docs += d.get("archives") or []
        if page >= ((d.get("_meta") or {}).get("totalPages") or page):
            break
        page += 1
    print(f"archives in posting window {p0}..{p1}: {len(docs)}", flush=True)
    for k, a in enumerate(sorted(docs, key=lambda x: x["postDatetime"])):
        raw = None
        try:
            raw = get(a["_links"]["endpoint"]["href"])
            z = zipfile.ZipFile(io.BytesIO(raw))
        except Exception as e:
            print(f"  skip {a['postDatetime']}: {e}", flush=True)
            continue
        agg = defaultdict(lambda: [0.0, 0.0, 0.0, 0])  # (day, he, resource, type) -> sums
        for n in z.namelist():
            if not any(key in n for key in KEEP):
                continue
            r = csv.reader(io.TextIOWrapper(z.open(n), encoding="latin-1"))
            hdr = next(r)
            ix = {h: i for i, h in enumerate(hdr)}
            ts, rn, rt = ix["SCED Time Stamp"], ix["Resource Name"], ix["Resource Type"]
            tno, bp, hsl = ix["Telemetered Net Output"], ix["Base Point"], ix["HSL"]
            for row in r:
                try:
                    t = datetime.strptime(row[ts], "%m/%d/%Y %H:%M:%S")
                    he = t.hour + 1
                    v = agg[(t.date(), he, row[rn], row[rt])]
                    v[0] += float(row[tno] or 0)
                    v[1] += float(row[bp] or 0)
                    v[2] += float(row[hsl] or 0)
                    v[3] += 1
                except (ValueError, IndexError):
                    continue
        days = sorted({key[0] for key in agg})
        for day in days:
            if not (d0 <= day <= d1):
                continue
            f = out / f"{day}.csv.gz"
            if f.exists():
                continue
            with gzip.open(f, "wt", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["hour_ending", "resource", "type", "net_mw", "base_point_mw", "hsl_mw"])
                for (dd, he, res, typ), (s0, s1, s2, n) in sorted(agg.items()):
                    if dd == day:
                        w.writerow([he, res, typ, round(s0 / n, 2), round(s1 / n, 2), round(s2 / n, 2)])
        print(f"[{k + 1}/{len(docs)}] posted {a['postDatetime'][:10]} -> {', '.join(map(str, days))}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
