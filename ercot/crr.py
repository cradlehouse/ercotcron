"""CRR auction results from ERCOT's MIS.

A different source from everything else here: www.ercot.com rather than
api.ercot.com, no authentication, and zipped CSV rather than paged JSON. It is
worth the separate path because it carries the one number the price feeds
cannot — what a congestion right cost at auction. dam_spp says what a path
paid; without this, every spread is a payoff with no purchase price.

Note the host matters. The same report on mis.ercot.com redirects to SiteMinder
and requires a market-participant login; on www.ercot.com it is public.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime

import httpx

from . import config, db

log = logging.getLogger(__name__)

LISTING = "https://www.ercot.com/misapp/GetReports.do"
DOWNLOAD = "https://www.ercot.com/misdownload/servlets/mirDownload"

# ERCOT report type ids. Monthly auctions clear each month; long-term auctions
# sell multi-month strips twice a year.
REPORT_TYPES = {"monthly": "11201", "long_term": "11203"}

TIMEOUT = httpx.Timeout(180.0, connect=30.0)

AWARDS_FILE = "MarketResults"
POINT_PRICE_FILE = "SourceAndSinkShadowPrices"
BIDS_FILE = "AuctionBidsAndOffers"

# Every auction's raw zip is archived before parsing, because the source
# expires: the MIS listing returns exactly 12 monthly auctions, so each month
# silently deletes the oldest one and it cannot be recovered afterwards. Parsed
# rows are not a substitute — the column mapping was chosen before anyone knew
# what the analysis would need, and re-parsing requires the original file.
ARCHIVE_BUCKET = "crr-raw"


@dataclass
class Document:
    doc_id: str
    file_name: str
    auction_name: str


def _auction_name(file_name: str) -> str:
    """The auction label inside the report filename.

    Monthly and long-term auctions name themselves differently —
    `AUG2026MonthlyCRRAuctionResults.zip` against
    `20272nd6AnnualAuctionSeq3CRRAuctionResults.zip` — so match the whole
    segment before the suffix rather than a month-and-year shape.
    """
    m = re.search(r"\.([A-Za-z0-9]+)CRRAuctionResults\.zip$", file_name)
    return m.group(1) if m else file_name


def list_documents(report_type: str = "monthly") -> list[Document]:
    """Every auction result currently posted, newest first."""
    rtid = REPORT_TYPES[report_type]
    resp = httpx.get(LISTING, params={"reportTypeId": rtid}, timeout=TIMEOUT,
                     follow_redirects=True)
    resp.raise_for_status()
    html = resp.text

    # The listing pairs a doclookupId with the filename in the same row; parse
    # them together rather than zipping two independent findall results, which
    # would silently misalign if a row were ever missing one of the two.
    docs: list[Document] = []
    for row in re.split(r"<tr[^>]*>", html):
        doc = re.search(r"doclookupId=(\d+)", row)
        name = re.search(r"([A-Za-z0-9_.\-]+\.zip)", row)
        if doc and name:
            docs.append(Document(doc.group(1), name.group(1), _auction_name(name.group(1))))
    return docs


def fetch_bytes(doc_id: str) -> bytes:
    resp = httpx.get(DOWNLOAD, params={"doclookupId": doc_id}, timeout=TIMEOUT,
                     follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def fetch_zip(doc_id: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(fetch_bytes(doc_id)))


def _read_csv(zf: zipfile.ZipFile, marker: str) -> list[dict[str, str]]:
    names = [n for n in zf.namelist() if marker in n and n.lower().endswith(".csv")]
    if not names:
        return []
    with zf.open(names[0]) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))


def _date(value: str) -> str | None:
    """ERCOT writes MM/DD/YYYY here, unlike the ISO dates the API returns."""
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def _num(value: str) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _bid_price(r: dict[str, str]) -> float | None:
    """Bid price with tolerance for the column-name drift ERCOT has shown.

    Current files write BidPricePerMWH; BidPrice/Price are kept as fallbacks
    for older vintages. Reading only the fallbacks is what left crr_bids
    empty — no current file carries either.
    """
    for key in ("BidPricePerMWH", "BidPrice", "Price"):
        if key in r:
            return _num(r[key])
    return None


def archive_zip(doc: Document, blob: bytes) -> bool:
    """Store the raw zip. Failure must not stop the ingest."""
    url = config.supabase_url()
    key = config.supabase_service_key()
    if not url or not key:
        return False
    try:
        resp = httpx.post(
            f"{url}/storage/v1/object/{ARCHIVE_BUCKET}/{doc.file_name}",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/zip",
                     "x-upsert": "true"},
            content=blob, timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            log.warning("archive %s failed: %s %s", doc.file_name,
                        resp.status_code, resp.text[:160])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("archive %s failed: %s", doc.file_name, exc)
        return False


def ingest_auction(doc: Document, report_type: str = "monthly") -> dict[str, int]:
    """Load one auction's awards, bids and nodal prices. Idempotent."""
    blob = fetch_bytes(doc.doc_id)
    archived = archive_zip(doc, blob)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    awards = _read_csv(zf, AWARDS_FILE)
    prices = _read_csv(zf, POINT_PRICE_FILE)

    db.upsert_rows(
        "crr_auctions",
        ["auction_name", "report_type", "doc_lookup_id", "file_name", "awards"],
        [(doc.auction_name, report_type, doc.doc_id, doc.file_name, len(awards))],
        conflict=["auction_name"],
        update=["report_type", "doc_lookup_id", "file_name", "awards"],
    )

    award_rows = []
    for r in awards:
        start, end = _date(r.get("StartDate", "")), _date(r.get("EndDate", ""))
        if not r.get("CRR_ID") or not start or not end:
            continue
        award_rows.append((
            doc.auction_name, r["CRR_ID"], r.get("TimeOfUse") or "",
            r.get("AccountHolder"), r.get("HedgeType") or "", r.get("BidType") or "",
            r.get("CRRType"), r.get("Source") or "", r.get("Sink") or "",
            start, end, _num(r.get("MW", "")), _num(r.get("ShadowPricePerMWH", "")),
        ))

    inserted, updated = db.upsert_rows(
        "crr_awards",
        ["auction_name", "crr_id", "time_of_use", "account_holder", "hedge_type",
         "bid_type", "crr_type", "source", "sink", "start_date", "end_date",
         "mw", "clearing_price"],
        award_rows,
        conflict=["auction_name", "crr_id", "time_of_use"],
        update=["account_holder", "hedge_type", "bid_type", "crr_type", "source",
                "sink", "start_date", "end_date", "mw", "clearing_price"],
    )

    price_rows = [
        (doc.auction_name, r.get("SourceSink") or "", r.get("TimeOfUse") or "",
         r.get("CalendarPeriod"), _num(r.get("ShadowPricePerMWH", "")))
        for r in prices
        if r.get("SourceSink")
    ]
    p_ins, p_upd = db.upsert_rows(
        "crr_point_prices",
        ["auction_name", "settlement_point", "time_of_use", "calendar_period",
         "shadow_price"],
        price_rows,
        conflict=["auction_name", "settlement_point", "time_of_use"],
        update=["calendar_period", "shadow_price"],
    )

    # Losing bids are the behavioural record: what the market was willing to
    # pay for each path, not merely what cleared. The rows are anonymous curve
    # segments — no AccountHolder, no AwardedMW in this file — so identity is
    # position among BUY rows in file order, mirroring crr_offers, which takes
    # the same file's SELL rows (scripts/ingest_crr_offers.py).
    # Streamed in batches: the bids file is ~26MB and ~330k rows per auction,
    # and materialising it as Python dicts is several hundred MB — which is an
    # OOM kill on a 512MB instance, observed as a 502 fourteen seconds into the
    # request with a healthy service just before.
    BID_COLS = ["auction_name", "row_num", "source", "sink", "time_of_use",
                "hedge_type", "start_date", "end_date", "mw", "bid_price",
                "shadow_price"]
    BID_UPDATE = ["source", "sink", "time_of_use", "hedge_type", "start_date",
                  "end_date", "mw", "bid_price", "shadow_price"]
    b_seen = b_ins = 0
    names = [n for n in zf.namelist() if BIDS_FILE in n and n.lower().endswith(".csv")]
    if names:
        import csv as _csv
        with zf.open(names[0]) as fh:
            reader = _csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
            batch: list[tuple] = []
            row_num = 0
            for r in reader:
                if (r.get("BidType") or "").strip().upper() != "BUY":
                    continue
                # Counts every BUY row, skipped or not, so identity does not
                # shift if a currently-unparseable row ever starts parsing.
                row_num += 1
                start, end = _date(r.get("StartDate", "")), _date(r.get("EndDate", ""))
                if not start or not end:
                    continue
                batch.append((
                    doc.auction_name, row_num,
                    r.get("Source") or "", r.get("Sink") or "",
                    r.get("TimeOfUse") or "", r.get("HedgeType") or "",
                    start, end, _num(r.get("MW", "")), _bid_price(r),
                    _num(r.get("ShadowPricePerMWH", "")),
                ))
                if len(batch) >= 50_000:
                    ins, _ = db.upsert_rows("crr_bids", BID_COLS, batch,
                                            conflict=["auction_name", "row_num"],
                                            update=BID_UPDATE)
                    b_seen += len(batch); b_ins += ins; batch = []
            if batch:
                ins, _ = db.upsert_rows("crr_bids", BID_COLS, batch,
                                        conflict=["auction_name", "row_num"],
                                        update=BID_UPDATE)
                b_seen += len(batch); b_ins += ins

    log.info("crr %s: %d awards (%d new), %d prices, %d bids, archived=%s",
             doc.auction_name, len(award_rows), inserted, len(price_rows),
             b_seen, archived)
    return {
        "auction": doc.auction_name,
        "archived": archived,
        "bids_seen": b_seen, "bids_new": b_ins,
        "awards_seen": len(award_rows), "awards_new": inserted, "awards_updated": updated,
        "point_prices_seen": len(price_rows), "point_prices_new": p_ins,
        "point_prices_updated": p_upd,
    }


def ingest_recent(limit: int = 3, report_type: str = "monthly") -> dict[str, object]:
    """Load the newest `limit` auctions. The scheduled entry point."""
    docs = [d for d in list_documents(report_type)
            if "CRRAuctionResults" in d.file_name][:limit]
    results, failures = [], []
    for d in docs:
        try:
            results.append(ingest_auction(d, report_type))
        except Exception as exc:  # noqa: BLE001
            # One unreadable download must not discard the auctions that did
            # load. The long-term batch failed entirely on a single file that
            # came back as something other than a zip.
            log.warning("crr %s failed: %s", d.auction_name, exc)
            failures.append({"auction": d.auction_name, "error": str(exc)})
    return {
        "auctions": len(results),
        "failed": len(failures),
        "awards_seen": sum(r["awards_seen"] for r in results),
        "awards_new": sum(r["awards_new"] for r in results),
        "detail": results,
        "failures": failures,
    }


def ingest_job(_client: object = None, limit: int = 2,
               report_type: str = "monthly") -> "Result":  # noqa: F821
    """Scheduler entry point.

    Takes and ignores an ErcotClient so it matches the Job signature. CRR
    reports come from www.ercot.com without authentication, so the API's bearer
    token and rate limiter are irrelevant here — and deliberately unused, since
    borrowing them would put MIS downloads under the API's request budget for
    no reason.
    """
    from .ingest import Result

    out = ingest_recent(limit=limit, report_type=report_type)
    # The P&L view is materialised, so new awards are invisible until it is
    # rebuilt. Refreshing here keeps "ingested" and "queryable" the same event.
    try:
        db.refresh_crr_pnl()
    except Exception as exc:  # noqa: BLE001 — a stale view must not fail ingest
        log.warning("crr_pnl refresh failed (data is loaded, view is stale): %s", exc)
    result = Result()
    result.rows_seen = int(out["awards_seen"])
    result.rows_inserted = int(out["awards_new"])
    return result
