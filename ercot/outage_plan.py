"""ERCOT's planned outage capacity plan (NP3-161-CD), one edition a day, kept.

"Available Resource Planned Outage Capacity Margin, 7 Day Plus": system-wide MW
of resources scheduled out, per operating day, from ~7 days to ~5 years ahead.
ERCOT keeps only ~3.5 months of past editions, so the plan as it stood on any
auction date is lost unless it is saved daily. Each edition lands in
ercot_forecast_vintages as one row per column: delivery_date is the edition's
first operating date and vals is the DAILY series from there.
"""

from __future__ import annotations

import csv
import io
import itertools
import logging
import zipfile
from datetime import date, datetime, timedelta

from . import db
from .client import ErcotClient
from .ingest import Result

log = logging.getLogger(__name__)

PRODUCT = "NP3-161-CD"


def edition_rows(posted: datetime, text: str) -> list[tuple]:
    """CSV text of one edition -> table rows. Raises if the dates are not a
    contiguous daily run (a malformed edition is skipped, never half-stored)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("empty edition")
    dates = [datetime.strptime(r["OperatingDate"], "%m/%d/%Y").date() for r in rows]
    if any((b - a).days != 1 for a, b in itertools.pairwise(dates)):
        raise ValueError("operating dates are not a contiguous daily run")
    out = []
    for col in rows[0]:
        if col == "OperatingDate":
            continue
        vals: list[float | None] = []
        for r in rows:
            try:
                vals.append(float(r[col]))
            except (TypeError, ValueError):
                vals.append(None)
        out.append((PRODUCT, posted, dates[0], col, vals))
    return out


def ingest_planned_outage_cap(client: ErcotClient, days_back: int = 4) -> Result:
    result = Result()
    since = date.today() - timedelta(days=days_back)
    listing = client.get(f"/archive/{PRODUCT}", {"postDatetimeFrom": f"{since}T00:00:00", "size": 100})
    result.requests += 1
    latest: dict[str, dict] = {}
    for a in listing.get("archives") or []:
        k = a["postDatetime"][:10]
        if k not in latest or a["postDatetime"] > latest[k]["postDatetime"]:
            latest[k] = a
    with db.connection() as conn:
        have = {r[0] for r in conn.execute(
            "select distinct posted_at::date from ercot_forecast_vintages where product = %s and posted_at >= %s",
            (PRODUCT, since))}
    for k, a in sorted(latest.items()):
        if date.fromisoformat(k) in have:
            continue
        blob = client.download(a["_links"]["endpoint"]["href"])
        result.requests += 1
        z = zipfile.ZipFile(io.BytesIO(blob))
        text = z.read(z.namelist()[0]).decode("latin-1")
        rows = edition_rows(datetime.fromisoformat(a["postDatetime"][:19]), text)
        result.rows_seen += len(rows)
        with db.connection() as conn:
            with conn.cursor() as cur, cur.copy("copy ercot_forecast_vintages from stdin") as cp:
                for row in rows:
                    cp.write_row(row)
            conn.commit()
        result.rows_inserted += len(rows)
        log.info("planned outage plan: saved edition posted %s (%d series)", a["postDatetime"], len(rows))
    return result
