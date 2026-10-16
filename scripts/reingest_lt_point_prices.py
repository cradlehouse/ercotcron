#!/usr/bin/env python3
"""Reload node prices for every long-term CRR auction still on ERCOT's public
listing, after the key fix (migration 20261016120000). Prices only: awards and
bids are untouched. Idempotent.

    python scripts/reingest_lt_point_prices.py
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ercot import crr, db


def main() -> int:
    docs = crr.list_documents("long_term")
    with db.connection() as conn:
        have = {r[0] for r in conn.execute("select auction_name from crr_auctions")}
    total = 0
    for d in docs:
        if d.auction_name not in have:
            print(f"skip {d.auction_name}: not loaded (the daily job loads new auctions)", flush=True)
            continue
        zf = zipfile.ZipFile(io.BytesIO(crr.fetch_bytes(d.doc_id)))
        prices = crr._read_csv(zf, crr.POINT_PRICE_FILE)
        ins, upd = crr.upsert_point_prices(d.auction_name, prices)
        total += ins
        print(f"{d.auction_name}: {len(prices)} rows in file, {ins} inserted, {upd} updated", flush=True)
    print(f"done: {total} rows inserted across {len(docs)} listed auctions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
