#!/usr/bin/env python3
"""Ingest ERCOT's public large-load queue numbers — which are aggregates only.

    python scripts/ingest_large_load.py --parse-only \
        --url https://www.ercot.com/files/docs/2026/03/12/March-TAC-Report.pdf

WHAT EXISTS PUBLICLY, verified 2026-08-15: per-project large-load queue data
is confidential. NPRR1267 (PUCT-approved 2025-07-31) mandates a public
monthly Large Load Interconnection Status Report, but it is not implemented
yet — it appears in no EMIL data product (all 5,824 checked), no MIS report
type, and no api.ercot.com product. The public record is the monthly "Large
Load Interconnection Status Update" deck the Large Load Integration Team
presents at TAC. Most of that deck's figures live inside chart images; only
the narrative sentences are machine-readable. This script extracts those:

  - approved_to_energize_mw     "Of the 9042 MW that have received Approval…"
  - nonsimultaneous_peak_mw     "non-simultaneous monthly peak consumption of…"
  - simultaneous_peak_mw        "observed a simultaneous monthly peak…"
  - new_submissions(+_mw)       "received 137 new LLI submissions… 140,000 MW"

There is no stable URL or index for the decks (they land in per-meeting TAC
material bundles with ad-hoc names), so the deck URL is an argument. When
ERCOT ships the NPRR1267 report, replace this scraper with a real parser and
a per-project table.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys
from datetime import date, datetime

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import pypdf  # noqa: E402

TIMEOUT = httpx.Timeout(180.0, connect=30.0)

# The most recent deck known to carry the LLI status update section.
DEFAULT_URL = "https://www.ercot.com/files/docs/2026/03/12/March-TAC-Report.pdf"

COLUMNS = ["report_month", "metric", "category", "mw", "projects",
           "source_url", "note"]
INSERT = f"""
insert into large_load_queue ({", ".join(COLUMNS)})
values ({", ".join(["%s"] * len(COLUMNS))})
on conflict (report_month, metric, category) do update set
  mw = excluded.mw, projects = excluded.projects,
  source_url = excluded.source_url, note = excluded.note
"""

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def _sentence(text: str, pos: int) -> str:
    """The sentence-ish neighbourhood a match came from, for the note column."""
    lo = max(0, pos - 120)
    return re.sub(r"\s+", " ", text[lo:pos + 160]).strip()


def parse_deck(blob: bytes, url: str) -> tuple[date | None, list[tuple]]:
    reader = pypdf.PdfReader(io.BytesIO(blob))
    pages = [p.extract_text() or "" for p in reader.pages]
    text = "\n".join(pages)

    # The deck's own date sits on the title slide: "March 13, 2026"
    month = None
    m = re.search(r"(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s+\d{1,2},\s+(\d{4})",
                  pages[0] if pages else "")
    if m:
        month = date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)

    rows: list[tuple] = []

    def add(metric, mw=None, projects=None, at=0):
        rows.append((month, metric, "", mw, projects, url, _sentence(text, at)))

    # PDF text extraction breaks lines mid-sentence, so every literal space in
    # these patterns must tolerate a newline.
    def rx(pattern):
        return re.search(pattern.replace(" ", r"\s+"), text)

    m = rx(r"Of the ([\d,]+) MW that have received Approval to Energize")
    if m:
        add("approved_to_energize_mw", mw=_n(m.group(1)), at=m.start())
    m = rx(r"non-simultaneous monthly peak consumption of ([\d,]+) MW")
    if m:
        add("nonsimultaneous_peak_mw", mw=_n(m.group(1)), at=m.start())
    m = rx(r"(?<!non-)simultaneous monthly peak consumption of ([\d,]+) MW")
    if m:
        add("simultaneous_peak_mw", mw=_n(m.group(1)), at=m.start())
    m = rx(r"received (\d+) new LLI submissions")
    if m:
        count = int(m.group(1))
        at = m.start()
        m2 = rx(r"approximately ([\d,]+) MW of new Large Load")
        add("new_lli_submissions", projects=count,
            mw=_n(m2.group(1)) if m2 else None, at=at)

    return month, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL,
                    help="URL of a Large Load Interconnection Status Update deck")
    ap.add_argument("--parse-only", action="store_true",
                    help="download and parse, print a summary, write nothing")
    args = ap.parse_args()

    print("source:", args.url, flush=True)
    resp = httpx.get(args.url, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    month, rows = parse_deck(resp.content, args.url)

    print(f"report_month={month}, extracted {len(rows)} aggregate metrics")
    for r in rows[:4]:
        print("sample:", dict(zip(COLUMNS, r)))
    if not rows:
        print("WARNING: nothing extracted — the deck layout may have changed")
        return 1

    if args.parse_only:
        return 0
    if month is None:
        raise SystemExit("cannot ingest without a report date on the title slide")

    import os
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT, rows)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("select report_month, metric, mw, projects "
                        "from large_load_queue order by report_month desc, metric limit 8")
            for row in cur.fetchall():
                print("  ", row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
