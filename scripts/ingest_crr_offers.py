#!/usr/bin/env python3
"""Ingest CRR auction OFFERS — the sell side of the bids-and-offers file.

    python scripts/ingest_crr_offers.py --parse-only        # newest auction, no DB
    python scripts/ingest_crr_offers.py --auction AUG2026Monthly

An offer is an existing holder selling out of a position: which paths current
holders no longer want, and the least they will accept to shed them. The rows
live in the same Common_AuctionBidsAndOffers CSV that ercot/crr.py already
downloads for bids, distinguished by BidType = SELL (~70k of ~330k rows in a
monthly auction).

The file's actual columns (2026 vintage): Source, Sink, BidType, StartDate,
EndDate, HedgeType, TimeOfUse, MW, BidPricePerMWH, ShadowPricePerMWH. No
AccountHolder, no AwardedMW — offers are anonymous curve segments, so there
is no natural key; row_num (position among SELL rows in file order) is the
identity, stable for a published auction file.

NOTE while building this it emerged that crr_bids was empty: ercot/crr.py
read a "BidPrice"/"Price" column that these files do not have (it is
"BidPricePerMWH"), so every bid row was skipped as priceless. Fixed since —
crr.py now ingests the BUY rows keyed by row_num, mirroring this script.

Streamed and batched like crr.py's bid path — materialising the 26MB CSV as
dicts is an OOM on a small instance.
"""
from __future__ import annotations

import argparse
import csv
import io
import pathlib
import sys
import zipfile
from datetime import datetime

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from ercot import crr  # noqa: E402  (public MIS listing + download, no auth)

COLUMNS = ["auction_name", "row_num", "source", "sink", "time_of_use",
           "hedge_type", "start_date", "end_date", "mw", "min_price",
           "shadow_price"]
INSERT = f"""
insert into crr_offers ({", ".join(COLUMNS)})
values ({", ".join(["%s"] * len(COLUMNS))})
on conflict (auction_name, row_num) do update set
  source = excluded.source, sink = excluded.sink,
  time_of_use = excluded.time_of_use, hedge_type = excluded.hedge_type,
  start_date = excluded.start_date, end_date = excluded.end_date,
  mw = excluded.mw, min_price = excluded.min_price,
  shadow_price = excluded.shadow_price
"""


def _date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%m/%d/%Y").date()


def _num(value: str):
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _price(r: dict):
    """Tolerate the column-name drift ERCOT has already demonstrated."""
    for key in ("BidPricePerMWH", "BidPrice", "Price"):
        if key in r:
            return _num(r[key])
    return None


def iter_offers(zf: zipfile.ZipFile, auction_name: str):
    names = [n for n in zf.namelist()
             if crr.BIDS_FILE in n and n.lower().endswith(".csv")]
    if not names:
        return
    row_num = 0
    with zf.open(names[0]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            if (r.get("BidType") or "").strip().upper() != "SELL":
                continue
            row_num += 1
            start, end = _date(r.get("StartDate", "")), _date(r.get("EndDate", ""))
            if not start or not end:
                continue
            yield (auction_name, row_num,
                   (r.get("Source") or "").strip(), (r.get("Sink") or "").strip(),
                   (r.get("TimeOfUse") or "").strip(),
                   (r.get("HedgeType") or "").strip(),
                   start, end, _num(r.get("MW", "")), _price(r),
                   _num(r.get("ShadowPricePerMWH", "")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auction", help="auction name, e.g. AUG2026Monthly "
                                      "(default: newest posted)")
    ap.add_argument("--report-type", default="monthly",
                    choices=["monthly", "long_term"])
    ap.add_argument("--parse-only", action="store_true",
                    help="download and parse, print a summary, write nothing")
    args = ap.parse_args()

    docs = [d for d in crr.list_documents(args.report_type)
            if "CRRAuctionResults" in d.file_name]
    if args.auction:
        docs = [d for d in docs if d.auction_name == args.auction]
    if not docs:
        raise SystemExit("no matching auction in the MIS listing")
    doc = docs[0]
    print(f"auction: {doc.auction_name} ({doc.file_name})", flush=True)

    zf = crr.fetch_zip(doc.doc_id)

    if args.parse_only:
        n = 0
        cleared = 0
        samples = []
        for row in iter_offers(zf, doc.auction_name):
            n += 1
            if row[9] is not None and row[10] is not None and row[10] >= row[9]:
                cleared += 1
            if len(samples) < 2:
                samples.append(row)
        print(f"offers parsed: {n} ({cleared} would clear at the shadow price)")
        for s in samples:
            print("sample:", dict(zip(COLUMNS, s)))
        return 0

    import os
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn:
        conn.execute("set statement_timeout='10min'")
        with conn.cursor() as cur:
            cur.execute("select to_regclass('crr_offers')")
            if cur.fetchone()[0] is None:
                raise SystemExit("crr_offers does not exist — apply "
                                 "supabase/migrations/20260815120400_crr_offers.sql first")
            # The FK needs the auction row; crr.py normally creates it, but
            # an auction being ingested for offers before awards should not
            # fail on ordering.
            cur.execute("insert into crr_auctions (auction_name, report_type, "
                        "doc_lookup_id, file_name, awards) values (%s,%s,%s,%s,0) "
                        "on conflict (auction_name) do nothing",
                        (doc.auction_name, args.report_type, doc.doc_id, doc.file_name))
            batch, total = [], 0
            for row in iter_offers(zf, doc.auction_name):
                batch.append(row)
                if len(batch) >= 20_000:
                    cur.executemany(INSERT, batch)
                    conn.commit()
                    total += len(batch)
                    batch = []
                    print(f"  {total} offers loaded", flush=True)
            if batch:
                cur.executemany(INSERT, batch)
                conn.commit()
                total += len(batch)
        with conn.cursor() as cur:
            cur.execute("select count(*), count(*) filter (where cleared) "
                        "from crr_offers where auction_name = %s",
                        (doc.auction_name,))
            print(f"crr_offers[{doc.auction_name}]:", cur.fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
