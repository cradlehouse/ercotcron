#!/usr/bin/env python3
"""Backfill binding transmission constraints and shadow prices (NP6-86-CD).

    python scripts/backfill_constraints.py --days 365

Runs locally against DATABASE_URL rather than through the Render service, so it
needs no deploy and cannot disturb the scheduled jobs. It still goes through
ErcotClient, so the shared 24-req/min rate limiter applies.

Why this table matters more than its size suggests: congestion rent in ERCOT is
extremely concentrated — the June 2026 operations report shows the top ten
constraints carrying 47% of $172.7M. Forward-pricing a CRR therefore means
forecasting a few dozen constraints, not 35,000 paths. This is the history that
makes that possible; without it the PTDF engine has shift factors but nothing
to multiply them by.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from ercot import config  # noqa: E402
from ercot.client import ErcotClient  # noqa: E402
from ercot.fundamentals import CONSTRAINT_EP, _num, field  # noqa: E402
from ercot.timeutil import is_repeat_hour, parse_ercot_timestamp  # noqa: E402

COLS = ("sced_timestamp", "constraint_id", "contingency", "constraint_name",
        "shadow_price", "max_shadow_price", "limit_mw", "value_mw",
        "violated_mw", "from_station", "to_station", "from_kv", "to_kv",
        "cct_status")

INSERT = f"""
insert into binding_constraints ({",".join(COLS)})
values ({",".join(["%s"] * len(COLS))})
on conflict (sced_timestamp, constraint_id, contingency) do update set
  shadow_price = excluded.shadow_price,
  max_shadow_price = excluded.max_shadow_price,
  limit_mw = excluded.limit_mw,
  value_mw = excluded.value_mw,
  violated_mw = excluded.violated_mw
"""


def window_rows(client: ErcotClient, lo: datetime, hi: datetime):
    def ts(m):
        return m.astimezone(config.CENTRAL).strftime("%Y-%m-%dT%H:%M:%S")

    seen = {}
    for raw in client.rows(CONSTRAINT_EP, {"SCEDTimestampFrom": ts(lo),
                                           "SCEDTimestampTo": ts(hi)}):
        stamp = field(raw, "SCEDTimestamp", "scedTimestamp")
        cid = field(raw, "constraintID", "constraintId")
        contingency = field(raw, "contingencyName", "contingency")
        if stamp is None or cid is None:
            continue
        repeat = is_repeat_hour(field(raw, "repeatedHourFlag", "repeatHourFlag", "DSTFlag"))
        try:
            sced = parse_ercot_timestamp(stamp, repeated=repeat)
        except ValueError:
            continue
        key = (sced, int(cid), contingency or "")
        seen[key] = (sced, int(cid), contingency or "",
                     field(raw, "constraintName"),
                     _num(field(raw, "shadowPrice")),
                     _num(field(raw, "maxShadowPrice")),
                     _num(field(raw, "limit")),
                     _num(field(raw, "value")),
                     _num(field(raw, "violatedMW")),
                     field(raw, "fromStation"),
                     field(raw, "toStation"),
                     _num(field(raw, "fromStationkV")),
                     _num(field(raw, "toStationkV")),
                     field(raw, "CCTStatus"))
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--chunk-hours", type=int, default=24,
                    help="window per request; smaller if the report is wide")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn or "YOUR-PASSWORD" in dsn:
        print("DATABASE_URL not configured")
        return 1

    client = ErcotClient()
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    step = timedelta(hours=args.chunk_hours)

    total_seen = total_written = 0
    windows = int((end - start) / step)
    print(f"backfilling constraints {start:%Y-%m-%d} .. {end:%Y-%m-%d} "
          f"({windows} windows of {args.chunk_hours}h)", flush=True)

    with psycopg.connect(dsn, connect_timeout=30) as conn:
        conn.execute("set statement_timeout='10min'")
        lo = start
        i = 0
        while lo < end:
            hi = min(lo + step, end)
            i += 1
            try:
                rows = window_rows(client, lo, hi)
            except Exception as exc:
                print(f"  [{i}/{windows}] {lo:%Y-%m-%d} FAILED: {str(exc)[:90]}", flush=True)
                lo = hi
                continue
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(INSERT, rows)
                conn.commit()
            total_seen += len(rows)
            total_written += len(rows)
            if i % 10 == 0 or rows:
                print(f"  [{i}/{windows}] {lo:%Y-%m-%d} +{len(rows):,} "
                      f"(total {total_written:,})", flush=True)
            lo = hi

        with conn.cursor() as cur:
            cur.execute("select count(*), min(sced_timestamp), max(sced_timestamp) "
                        "from binding_constraints")
            print("\nbinding_constraints now:", cur.fetchone())
            cur.execute("""select constraint_name, count(*) n,
                                  round(avg(shadow_price)::numeric,1) avg_sp
                             from binding_constraints
                            group by 1 order by n desc limit 10""")
            print("most frequently binding:")
            for r in cur.fetchall():
                print("   ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
