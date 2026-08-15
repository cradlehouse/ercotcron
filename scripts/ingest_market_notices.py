#!/usr/bin/env python3
"""Ingest ERCOT market notices — the public trace of network model changes.

    python scripts/ingest_market_notices.py --parse-only --days 30 --details 2
    python scripts/ingest_market_notices.py --days 90

NOMCR reality check, verified 2026-08-15 against the full EMIL catalog: the
actual NOMCR products (NP3-107-UI Network Operations Model Change Requests,
NP3-452-SG Status Changes, NP3-625-SG Summary) are all Certified — secure
MIS, ModelEditor/EWS, market participants only. The NOMCR notice products
(NP3-39/41-AN) are alerts to the requestor, not postings. There is no public
NOMCR feed.

What IS public: the market notice archive at
https://www.ercot.com/services/comm/mkt_notices/archives — server-rendered
HTML, ~3-year rolling window, with detail pages per notice. Model loads,
topology changes, GTC retirements and constraint methodology changes all
surface here. We ingest the whole stream (it is small) and flag the
model-related subset with a keyword match, so the filter can evolve without
having discarded anything.

Notice ids repeat when ERCOT posts corrections; the archive lists newest
first and the first occurrence wins, so the corrected version is kept.
"""
from __future__ import annotations

import argparse
import html as htmllib
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

BASE = "https://www.ercot.com"
ARCHIVE = BASE + "/services/comm/mkt_notices/archives"
TIMEOUT = httpx.Timeout(60.0, connect=30.0)

NOTICE_ID_RX = re.compile(r"\b([A-Z]-[A-Z]\d{6}-\d{2})\b")
ROW_RX = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(\d{2}/\d{2}/\d{4})\s*</td>\s*<td[^>]*>(.*?)</td>",
    re.S)
HREF_RX = re.compile(r'href="(/services/comm/mkt_notices/[^"]+)"')

MODEL_RX = re.compile(
    r"network operations model|model load|nomcr|topolog|"
    r"generic transmission|\bGTC\b|constraint|state estimator|"
    r"planning model|network model", re.I)

COLUMNS = ["notice_id", "posted_at", "title", "notice_type", "audience",
           "days_affected", "effective_date", "body", "url",
           "is_model_related"]
INSERT = f"""
insert into model_change_notices ({", ".join(COLUMNS)})
values ({", ".join(["%s"] * len(COLUMNS))})
on conflict (notice_id) do update set
  posted_at = excluded.posted_at, title = excluded.title,
  notice_type = excluded.notice_type, audience = excluded.audience,
  days_affected = excluded.days_affected,
  effective_date = excluded.effective_date, body = excluded.body,
  url = excluded.url, is_model_related = excluded.is_model_related
"""


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = htmllib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def list_notices(sd: date, ed: date, pages: int = 5) -> list[dict]:
    """Archive rows in the window, newest first. First occurrence of an id wins."""
    out: dict[str, dict] = {}
    for page in range(1, pages + 1):
        resp = httpx.get(ARCHIVE, params={
            "category": "", "keyword": "", "sd": sd.isoformat(),
            "ed": ed.isoformat(), "page": page, "pageSize": 100,
        }, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        rows = ROW_RX.findall(resp.text)
        if not rows:
            break
        for posted, cell in rows:
            title = _clean(cell)
            m = NOTICE_ID_RX.search(title)
            if not m:
                continue
            nid = m.group(1)
            href = HREF_RX.search(cell)
            if nid not in out:
                out[nid] = {
                    "notice_id": nid,
                    "posted_at": datetime.strptime(posted, "%m/%d/%Y").date(),
                    "title": title,
                    "url": BASE + href.group(1) if href
                           else f"{BASE}/services/comm/mkt_notices/{nid}",
                }
        if len(rows) < 100:
            break
    return list(out.values())


FIELDS = ["NOTICE DATE:", "NOTICE TYPE:", "SHORT DESCRIPTION:",
          "INTENDED AUDIENCE:", "DAYS AFFECTED:", "LONG DESCRIPTION:",
          "CONTACT:"]


def fetch_detail(url: str) -> dict:
    """The labelled fields from a notice detail page."""
    resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    text = _clean(re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                         resp.text, flags=re.S))
    got: dict[str, str] = {}
    for i, label in enumerate(FIELDS):
        start = text.find(label)
        if start < 0:
            continue
        start += len(label)
        ends = [text.find(nxt, start) for nxt in FIELDS[i + 1:]]
        ends = [e for e in ends if e >= 0]
        got[label] = text[start:min(ends)].strip() if ends else text[start:start + 4000].strip()
    days = got.get("DAYS AFFECTED:")
    effective = None
    if days:
        m = re.search(r"(January|February|March|April|May|June|July|August|"
                      r"September|October|November|December)\s+\d{1,2},\s+\d{4}", days)
        if m:
            try:
                effective = datetime.strptime(m.group(0), "%B %d, %Y").date()
            except ValueError:
                pass
    return {
        "notice_type": got.get("NOTICE TYPE:"),
        "audience": got.get("INTENDED AUDIENCE:"),
        "days_affected": days,
        "effective_date": effective,
        "body": got.get("LONG DESCRIPTION:"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90,
                    help="how far back to list (archive holds ~3 years)")
    ap.add_argument("--details", type=int, default=None,
                    help="fetch at most N detail pages (default: all listed)")
    ap.add_argument("--parse-only", action="store_true",
                    help="fetch and parse, print a summary, write nothing")
    args = ap.parse_args()

    ed = date.today()
    sd = ed - timedelta(days=args.days)
    notices = list_notices(sd, ed)
    print(f"listed {len(notices)} notices between {sd} and {ed}")

    limit = len(notices) if args.details is None else args.details
    rows: list[tuple] = []
    for n in notices:
        detail = fetch_detail(n["url"]) if len(rows) < limit else {}
        hay = " ".join(filter(None, [n["title"], detail.get("body")]))
        rows.append((
            n["notice_id"], n["posted_at"], n["title"],
            detail.get("notice_type"), detail.get("audience"),
            detail.get("days_affected"), detail.get("effective_date"),
            detail.get("body"), n["url"],
            bool(MODEL_RX.search(hay)),
        ))

    model = sum(1 for r in rows if r[9])
    print(f"parsed {len(rows)} notices ({model} model-related, "
          f"{min(limit, len(rows))} with detail bodies)")
    for r in rows[:2]:
        d = dict(zip(COLUMNS, r))
        d["body"] = (d["body"] or "")[:120]
        print("sample:", d)

    if args.parse_only:
        return 0

    import os
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT, rows)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("select count(*), count(*) filter (where is_model_related), "
                        "max(posted_at) from model_change_notices")
            print("model_change_notices:", cur.fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
