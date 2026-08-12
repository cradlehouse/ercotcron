#!/usr/bin/env python3
"""Ingest every CRR auction we don't already hold, locally.

The Render /crr endpoint failed on these (12 failures both types, cause not
yet diagnosed server-side); the listing works fine locally and we now have a
direct DB path, so the pragmatic fix is to run the same ingest from here.
Holder books are the foundation of the marks and alerts products — a mark on
a partial book is a wrong mark.
"""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from ercot import crr, db

existing = set()
try:
    with db.connection() as c:
        cur = c.cursor()
        cur.execute("select auction_name from crr_auctions")
        existing = {r[0] for r in cur.fetchall()}
except Exception as e:
    print("could not read existing:", e)
print(f"already held: {len(existing)}")

for rt in ("long_term", "monthly"):
    docs = crr.list_documents(rt)
    todo = [d for d in docs if d.auction_name not in existing]
    print(f"{rt}: {len(docs)} listed, {len(todo)} to ingest", flush=True)
    for d in todo:
        try:
            r = crr.ingest_auction(d, rt)
            print(f"  {d.auction_name}: {r}", flush=True)
        except Exception as e:
            print(f"  {d.auction_name}: FAILED {str(e)[:90]}", flush=True)
print("done")
