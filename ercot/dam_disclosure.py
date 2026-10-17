"""60-Day DAM Disclosure (NP3-966-ER), one operating day a day.

ERCOT posts each operating day's DAM awards 60 days later as one ~11 MB zip.
Writes, in one transaction per operating day (all three tables or none):
  dam_resource_awards  generator + storage awards, HSL and status per hour
  dam_virtual_awards   energy-only offer (injection) / bid (withdrawal) awards per settlement point
  dam_ptp_awards       PTP obligation/option awards per source-sink
Hours are arrays ordered by (hour ending, DST repeated-hour flag), so 23- and
25-hour days are exact. A day that fails validation is skipped and logged,
never half-written; a posted disclosure does not change, so days already in
the table are skipped. Parsing matches scripts/fetch_dam_disclosure.py (the
backfill loader) but streams the CSVs: the service runs on a small instance.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import config, db
from .client import ErcotClient
from .ingest import Result

log = logging.getLogger(__name__)

PRODUCT = "NP3-966-ER"

Slot = tuple[int, bool]


def _col(hdr: list[str], *needles: str) -> int | None:
    for i, h in enumerate(hdr):
        if all(n.lower() in h.lower() for n in needles):
            return i
    return None


def _member_rows(z: zipfile.ZipFile, key: str):
    """(header, row iterator) of the first member whose name contains key."""
    name = next((x for x in z.namelist() if key in x), None)
    if not name:
        return None, iter(())
    r = csv.reader(io.TextIOWrapper(z.open(name), encoding="latin-1"))
    return next(r, None), r


def _new_day() -> dict:
    return dict(slots=set(), res={}, virt=defaultdict(lambda: [{}, {}]), ptp=defaultdict(dict))


def parse(z: zipfile.ZipFile) -> dict[date, dict]:
    """-> {operating day: dict(slots, res, virt, ptp)}"""
    out: dict[date, dict] = defaultdict(_new_day)

    def slot(hdr: list[str], row: list[str]) -> tuple[date, Slot]:
        d = datetime.strptime(row[_col(hdr, "Delivery Date")], "%m/%d/%Y").date()
        he = int(row[_col(hdr, "Hour Ending")].split(":")[0])
        fi = _col(hdr, "DST")
        s = (he, (row[fi] or "N").upper() == "Y") if fi is not None else (he, False)
        out[d]["slots"].add(s)
        return d, s

    for key in ("Gen_Resource_Data", "ESR_Data"):
        hdr, rs = _member_rows(z, key)
        if not hdr:
            continue
        rn, rt, sp = _col(hdr, "Resource Name"), _col(hdr, "Resource Type"), _col(hdr, "Settlement Point Name")
        aw, hsl, st = _col(hdr, "Awarded Quantity"), _col(hdr, "HSL"), _col(hdr, "Resource Status")
        for row in rs:
            d, s = slot(hdr, row)
            rec = out[d]["res"].setdefault(row[rn], dict(type=row[rt], sp=row[sp], aw={}, hsl={}, st={}))
            rec["aw"][s] = float(row[aw]) if row[aw] else None
            rec["hsl"][s] = float(row[hsl]) if row[hsl] else None
            rec["st"][s] = row[st] or None
    for key, side in (("EnergyOnlyOfferAwards", 0), ("EnergyBidAwards", 1)):
        hdr, rs = _member_rows(z, key)
        if not hdr:
            continue
        sp, mw = _col(hdr, "Settlement Point"), _col(hdr, "Award in MW")
        for row in rs:
            d, s = slot(hdr, row)
            cell = out[d]["virt"][row[sp]][side]
            cell[s] = cell.get(s, 0.0) + float(row[mw] or 0)
    for key in ("PTP_Obligation_OptionAwards", "PTPObligationBidAwards"):
        hdr, rs = _member_rows(z, key)
        if not hdr:
            continue
        so, si = _col(hdr, "Source"), _col(hdr, "Sink")
        aw = _col(hdr, "Award")
        mw = aw if aw is not None and "id" not in hdr[aw].lower() else _col(hdr, "MW")
        for row in rs:
            d, s = slot(hdr, row)
            cell = out[d]["ptp"][(row[so], row[si])]
            cell[s] = cell.get(s, 0.0) + float(row[mw] or 0)
    return out


def validate(rec: dict) -> str | None:
    """Reason the day is unusable, or None."""
    slots = sorted(rec["slots"])
    if len(slots) not in (23, 24, 25):
        return f"{len(slots)} hourly slots"
    if len(rec["res"]) < 500:
        return f"only {len(rec['res'])} resources"
    gen = [sum((r["aw"].get(s) or 0) for r in rec["res"].values()) for s in slots]
    # floor catches broken files, not quiet days: 2025-01-04 is a complete file
    # (1,424 resources, normal award/status counts) peaking at 9.5 GW
    if not (5000 <= max(gen) <= 120000):
        return f"implausible peak generation award {max(gen):,.0f} MW"
    return None


def day_rows(day: date, rec: dict, posted: str) -> dict[str, list[tuple]]:
    """One validated day -> rows per table, arrays ordered by slot."""
    slots = sorted(rec["slots"])

    def arr(m: dict) -> list:
        return [m.get(s) for s in slots]

    return {
        "dam_resource_awards": [(day, n, r["type"], r["sp"], arr(r["aw"]), arr(r["hsl"]), arr(r["st"]), posted)
                                for n, r in rec["res"].items()],
        "dam_virtual_awards": [(day, sp, [v[0].get(s, 0.0) for s in slots], [v[1].get(s, 0.0) for s in slots], posted)
                               for sp, v in rec["virt"].items()],
        "dam_ptp_awards": [(day, so, si, [v.get(s, 0.0) for s in slots], posted)
                           for (so, si), v in rec["ptp"].items()],
    }


def ingest_dam_disclosure(client: ErcotClient, days_back: int = 5) -> Result:
    result = Result()
    since = datetime.now(config.CENTRAL).date() - timedelta(days=days_back)
    listing = client.get(f"/archive/{PRODUCT}", {"postDatetimeFrom": f"{since}T00:00:00", "size": 100})
    result.requests += 1
    archives = sorted(listing.get("archives") or [], key=lambda x: x["postDatetime"])
    # a posting covers the operating day ~60 days earlier; look a little wider
    lo = since - timedelta(days=70)
    with db.connection() as conn:
        stored = conn.execute(
            "select distinct delivery_date, source_posted_at at time zone 'UTC'"
            "  from dam_resource_awards where delivery_date >= %s", (lo,)).fetchall()
    have = {d for d, _ in stored}
    # Each ~11 MB posting is downloaded once: postDatetime is stored verbatim
    # (as UTC, the convention the backfill set), so a posting already saved is
    # recognised before it is fetched again.
    seen_posts = {p for _, p in stored if p is not None}
    rejected = []
    for a in archives:
        if datetime.fromisoformat(a["postDatetime"][:19]) in seen_posts:
            continue
        blob = client.download(a["_links"]["endpoint"]["href"])
        result.requests += 1
        parsed = parse(zipfile.ZipFile(io.BytesIO(blob)))
        del blob
        for day, rec in sorted(parsed.items()):
            if day in have:
                continue
            why = validate(rec)
            if why:
                log.warning("dam disclosure: rejected %s (posted %s): %s", day, a["postDatetime"], why)
                rejected.append(f"{day}: {why}")
                continue
            tables = day_rows(day, rec, a["postDatetime"])
            n = sum(len(rows) for rows in tables.values())
            result.rows_seen += n
            with db.connection() as conn:
                with conn.cursor() as cur:
                    for table, rows in tables.items():
                        with cur.copy(f"copy {table} from stdin") as cp:
                            for row in rows:
                                cp.write_row(row)
                conn.commit()
            have.add(day)
            result.rows_inserted += n
            log.info("dam disclosure: %s saved — %d resources, %d virtual points, %d PTP pairs",
                     day, *(len(rows) for rows in tables.values()))
    if rejected and not result.rows_inserted:
        # Postings existed but none was usable: fail loudly rather than let the
        # run read as a quiet day.
        raise ValueError(f"every new disclosure day failed validation: {rejected}")
    return result
