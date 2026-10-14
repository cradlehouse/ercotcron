#!/usr/bin/env python3
"""Load ERCOT's 60-Day DAM Disclosure (NP3-966-ER) into the database, hourly.

    python scripts/fetch_dam_disclosure.py --from 2024-10-01 --to 2026-08-31

One public zip per operating day (~11 MB, posted 60 days later). Writes:
  dam_resource_awards  generator + storage awards, HSL and status per hour
  dam_virtual_awards   energy-only offer (injection) / bid (withdrawal) awards per settlement point
  dam_ptp_awards       PTP obligation/option awards per source-sink
Hours are stored as arrays ordered by (hour ending, DST repeated-hour flag), so
23- and 25-hour days are exact. Each day is validated before writing (row
counts, array lengths, plausible generation totals); a day that fails is
skipped and reported, never half-written. Bulk COPY, one transaction per day:
a disclosure does not change once posted. Resumes by skipping loaded days.
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

API = "https://api.ercot.com/api/public-reports/archive/NP3-966-ER"


def col(hdr, *needles):
    for i, h in enumerate(hdr):
        if all(n.lower() in h.lower() for n in needles):
            return i
    return None


def rows_of(z, key):
    n = next((x for x in z.namelist() if key in x), None)
    if not n:
        return [], []
    r = csv.reader(io.TextIOWrapper(z.open(n), encoding="latin-1"))
    hdr = next(r)
    return hdr, list(r)


def parse(z):
    """-> {day: dict(slots=[...], res={...}, virt={...}, ptp={...})}"""
    out = defaultdict(lambda: dict(slots=set(), res={}, virt=defaultdict(lambda: [{}, {}]), ptp=defaultdict(dict)))

    def slot(hdr, row):
        d = datetime.strptime(row[col(hdr, "Delivery Date")], "%m/%d/%Y").date()
        he = int(row[col(hdr, "Hour Ending")].split(":")[0])
        fi = col(hdr, "DST")
        s = (he, (row[fi] or "N").upper() == "Y") if fi is not None else (he, False)
        out[d]["slots"].add(s)
        return d, s

    for key in ("Gen_Resource_Data", "ESR_Data"):
        hdr, rs = rows_of(z, key)
        if not hdr:
            continue
        rn, rt, sp = col(hdr, "Resource Name"), col(hdr, "Resource Type"), col(hdr, "Settlement Point Name")
        aw, hsl, st = col(hdr, "Awarded Quantity"), col(hdr, "HSL"), col(hdr, "Resource Status")
        for row in rs:
            d, s = slot(hdr, row)
            rec = out[d]["res"].setdefault(row[rn], dict(type=row[rt], sp=row[sp], aw={}, hsl={}, st={}))
            rec["aw"][s] = float(row[aw]) if row[aw] else None
            rec["hsl"][s] = float(row[hsl]) if row[hsl] else None
            rec["st"][s] = row[st] or None
    for key, side in (("EnergyOnlyOfferAwards", 0), ("EnergyBidAwards", 1)):
        hdr, rs = rows_of(z, key)
        if not hdr:
            continue
        sp, mw = col(hdr, "Settlement Point"), col(hdr, "Award in MW")
        for row in rs:
            d, s = slot(hdr, row)
            cell = out[d]["virt"][row[sp]][side]
            cell[s] = cell.get(s, 0.0) + float(row[mw] or 0)
    for key in ("PTP_Obligation_OptionAwards", "PTPObligationBidAwards"):
        hdr, rs = rows_of(z, key)
        if not hdr:
            continue
        so, si = col(hdr, "Source"), col(hdr, "Sink")
        mw = col(hdr, "Award") if col(hdr, "Award") is not None and "id" not in hdr[col(hdr, "Award")].lower() else col(hdr, "MW")
        for row in rs:
            d, s = slot(hdr, row)
            cell = out[d]["ptp"][(row[so], row[si])]
            cell[s] = cell.get(s, 0.0) + float(row[mw] or 0)
    return out


def validate(day, rec):
    slots = sorted(rec["slots"])
    n = len(slots)
    if n not in (23, 24, 25):
        return f"{n} hourly slots"
    if len(rec["res"]) < 500:
        return f"only {len(rec['res'])} resources"
    gen = [sum((r["aw"].get(s) or 0) for r in rec["res"].values()) for s in slots]
    # floor catches broken files, not quiet days: 2025-01-04 is a complete file
    # (1,424 resources, normal award/status counts) peaking at 9.5 GW
    if not (5000 <= max(gen) <= 120000):
        return f"implausible peak generation award {max(gen):,.0f} MW"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", required=True)
    ap.add_argument("--to", dest="d1", required=True)
    args = ap.parse_args()
    d0, d1 = date.fromisoformat(args.d0), date.fromisoformat(args.d1)
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

    p0, p1 = d0 + timedelta(days=55), d1 + timedelta(days=66)
    docs, page = [], 1
    while True:
        d = json.loads(get(f"{API}?size=1000&page={page}&postDatetimeFrom={p0}T00:00:00&postDatetimeTo={p1}T23:59:59"))
        docs += d.get("archives") or []
        if page >= ((d.get("_meta") or {}).get("totalPages") or page):
            break
        page += 1
    print(f"archives in posting window {p0}..{p1}: {len(docs)}", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("set statement_timeout='170s'")
        have = {r[0] for r in c.execute("select distinct delivery_date from dam_resource_awards where delivery_date between %s and %s", (d0, d1))}
    bad = []
    for k, a in enumerate(sorted(docs, key=lambda x: x["postDatetime"])):
        try:
            z = zipfile.ZipFile(io.BytesIO(get(a["_links"]["endpoint"]["href"])))
            parsed = parse(z)
        except Exception as e:
            print(f"  fetch/parse failed {a['postDatetime']}: {e}", flush=True)
            bad.append(a["postDatetime"])
            continue
        for day, rec in sorted(parsed.items()):
            if not (d0 <= day <= d1) or day in have:
                continue
            why = validate(day, rec)
            if why:
                print(f"  REJECT {day}: {why}", flush=True)
                bad.append(str(day))
                continue
            slots = sorted(rec["slots"])
            arr = lambda m: [m.get(s) for s in slots]  # noqa: E731
            posted = a["postDatetime"]
            res = [(day, n, r["type"], r["sp"], arr(r["aw"]), arr(r["hsl"]), arr(r["st"]), posted) for n, r in rec["res"].items()]
            virt = [(day, sp, [v[0].get(s, 0.0) for s in slots], [v[1].get(s, 0.0) for s in slots], posted)
                    for sp, v in rec["virt"].items()]
            ptp = [(day, so, si, [v.get(s, 0.0) for s in slots], posted) for (so, si), v in rec["ptp"].items()]
            with psycopg.connect(os.environ["DATABASE_URL"]) as c:
                c.execute("set statement_timeout='170s'")
                # one transaction per day: all three tables or none (days already
                # present are skipped above, so COPY never meets a duplicate)
                with c.cursor() as cur:
                    for table, rows in (("dam_resource_awards", res), ("dam_virtual_awards", virt), ("dam_ptp_awards", ptp)):
                        with cur.copy(f"copy {table} from stdin") as cp:
                            for row in rows:
                                cp.write_row(row)
                c.commit()
            have.add(day)
            print(f"[{k + 1}/{len(docs)}] {day}: {len(slots)}h, {len(res)} resources, {len(virt)} virtual points, {len(ptp)} PTP pairs", flush=True)
    print(f"done; rejected/failed: {bad or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
