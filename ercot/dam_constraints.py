"""Day-ahead binding constraints and shadow prices (NP4-191-CD), daily.

The DAM's own view of which constraints bind and how hard — the middle leg of
"auction says X, DAM says Y, RT delivered Z". ERCOT posts one small zip per
operating day once the DAM clears (~13:30 CT for the next day). Until this job
the table was only loaded by scripts/backfill_dam_constraints.py by hand, so it
went stale between catch-ups. Rows upsert on the table's primary key, so
re-reading a few days of archive each run is harmless and heals a missed day.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timedelta

from . import config, db
from .client import ErcotClient
from .ingest import Result

log = logging.getLogger(__name__)

PRODUCT = "NP4-191-CD"

UPSERT = """
insert into dam_constraints
  (delivery_date, hour_ending, constraint_id, constraint_name, contingency,
   limit_mw, value_mw, violated_mw, shadow_price,
   from_station, to_station, from_kv, to_kv)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (delivery_date, hour_ending, constraint_id, contingency)
do update set shadow_price = excluded.shadow_price,
              limit_mw = excluded.limit_mw, value_mw = excluded.value_mw,
              violated_mw = excluded.violated_mw
"""


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "", " ") else None
    except ValueError:
        return None


def file_rows(text: str) -> list[tuple]:
    """CSV text of one daily file -> dam_constraints rows (same parsing as the
    backfill script, so the two loaders never disagree on a row)."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            dd = datetime.strptime(r["DeliveryDate"].strip(), "%m/%d/%Y").date()
            he = int(r["HourEnding"].split(":")[0])
        except (ValueError, KeyError, AttributeError):
            continue
        rows.append((dd, he, int(_num(r.get("ConstraintID")) or 0),
                     (r.get("ConstraintName") or "").strip(),
                     (r.get("ContingencyName") or "").strip(),
                     _num(r.get("ConstraintLimit")), _num(r.get("ConstraintValue")),
                     _num(r.get("ViolationAmount")), _num(r.get("ShadowPrice")),
                     (r.get("FromStation") or "").strip() or None,
                     (r.get("ToStation") or "").strip() or None,
                     _num(r.get("FromStationkV")), _num(r.get("ToStationkV"))))
    return rows


def ingest_dam_constraints(client: ErcotClient, days_back: int = 4) -> Result:
    result = Result()
    since = datetime.now(config.CENTRAL).date() - timedelta(days=days_back)
    listing = client.get(f"/archive/{PRODUCT}", {"postDatetimeFrom": f"{since}T00:00:00", "size": 100})
    result.requests += 1
    for a in sorted(listing.get("archives") or [], key=lambda x: x["postDatetime"]):
        blob = client.download(a["_links"]["endpoint"]["href"])
        result.requests += 1
        z = zipfile.ZipFile(io.BytesIO(blob))
        rows = file_rows(z.read(z.namelist()[0]).decode("utf8", "ignore"))
        result.rows_seen += len(rows)
        if not rows:
            continue
        with db.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPSERT, rows)
            conn.commit()
        result.rows_inserted += len(rows)
        log.info("dam constraints: file posted %s, %d rows (delivery %s)",
                 a["postDatetime"], len(rows), rows[0][0])
    return result
