"""ERCOT forecasts as they stood at the DAM deadline, one edition a day.

ERCOT re-issues its forecasts hourly. For each posting day we keep the edition
posted at 09:30 Central (else the latest posted 08:00-09:59) — the last before
the 10:00 DAM bid deadline — and store every numeric column, per delivery
date, as an hour array in ercot_forecast_vintages (ordered by hour ending,
DST flag). Same rule and row shape as scripts/fetch_forecast_vintages.py, the
backfill loader. An edition with fewer than 7 complete delivery days is
skipped and reported, never half-stored.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta

from . import config, db
from .client import ErcotClient
from .ingest import Result

log = logging.getLogger(__name__)

_SKIP = {"deliverydate", "hourending", "dstflag"}


def pick_edition(archives: list[dict]) -> dict | None:
    """The 09:30 edition, else the latest in the list."""
    arcs = sorted(archives, key=lambda a: a["postDatetime"])
    return next((a for a in arcs if a["postDatetime"][11:16] == "09:30"), arcs[-1] if arcs else None)


def edition_rows(product: str, posted: datetime, text: str) -> list[tuple]:
    """CSV text of one edition -> table rows. Raises if fewer than 7 delivery
    days are complete (23-25 hours)."""
    r = csv.reader(io.StringIO(text))
    hdr = next(r)
    low = [x.strip().lower().replace("_", "") for x in hdr]
    di, hi = low.index("deliverydate"), low.index("hourending")
    fi = low.index("dstflag") if "dstflag" in low else None
    series = [i for i, x in enumerate(low) if x not in _SKIP]
    cells: dict[tuple, dict] = defaultdict(dict)   # (date, column) -> {(he, dst): v}
    slots: dict = defaultdict(set)
    for row in r:
        if not row:
            continue
        dd = datetime.strptime(row[di], "%m/%d/%Y").date()
        s = (int(row[hi].split(":")[0]), fi is not None and row[fi].upper() == "Y")
        slots[dd].add(s)
        for i in series:
            try:
                cells[(dd, hdr[i].strip())][s] = float(row[i]) if row[i] not in ("", None) else None
            except ValueError:
                pass
    ok_days = {dd for dd, ss in slots.items() if 23 <= len(ss) <= 25}
    if len(ok_days) < 7:
        raise ValueError(f"only {len(ok_days)} complete delivery days")
    return [(product, posted, dd, col, [vals.get(s) for s in sorted(slots[dd])])
            for (dd, col), vals in cells.items() if dd in ok_days]


def ingest_forecast_vintage(client: ErcotClient, product: str, days_back: int = 4) -> Result:
    result = Result()
    today = datetime.now(config.CENTRAL).date()
    since = today - timedelta(days=days_back)
    with db.connection() as conn:
        have = {r[0] for r in conn.execute(
            "select distinct posted_at::date from ercot_forecast_vintages where product = %s and posted_at >= %s",
            (product, since))}
    problems = []
    day = since
    while day <= today:
        if day in have:
            day += timedelta(days=1)
            continue
        listing = client.get(f"/archive/{product}", {
            "postDatetimeFrom": f"{day}T08:00:00", "postDatetimeTo": f"{day}T09:59:59", "size": 100})
        result.requests += 1
        pick = pick_edition(listing.get("archives") or [])
        if pick is None:
            if day < today:     # today's may simply not be posted yet
                problems.append(f"{day}: no edition 08:00-09:59")
            day += timedelta(days=1)
            continue
        blob = client.download(pick["_links"]["endpoint"]["href"])
        result.requests += 1
        z = zipfile.ZipFile(io.BytesIO(blob))
        text = z.read(z.namelist()[0]).decode("latin-1")
        try:
            rows = edition_rows(product, datetime.fromisoformat(pick["postDatetime"][:19]), text)
        except ValueError as exc:
            problems.append(f"{day}: {exc}")
            day += timedelta(days=1)
            continue
        result.rows_seen += len(rows)
        with db.connection() as conn:
            with conn.cursor() as cur, cur.copy("copy ercot_forecast_vintages from stdin") as cp:
                for row in rows:
                    cp.write_row(row)
            conn.commit()
        result.rows_inserted += len(rows)
        log.info("%s: saved edition posted %s (%d rows)", product, pick["postDatetime"], len(rows))
        day += timedelta(days=1)
    if problems:
        log.warning("%s: skipped %s", product, problems)
    return result
