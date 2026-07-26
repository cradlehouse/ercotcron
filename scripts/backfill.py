#!/usr/bin/env python3
"""Historical loads. Run locally, not on a schedule.

This is also the disaster recovery plan: every price is reconstructible from
ERCOT, which is why the Supabase point-in-time-recovery add-on is not worth
$100/mo here. What backfill cannot reconstruct is the *revision* timeline —
posted_at, price_from and forecast vintages are only observable live.

    python scripts/backfill.py --market dam --start 2026-07-01 --end 2026-07-05
    python scripts/backfill.py --market rt  --start 2026-07-01 --end 2026-07-05
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ercot import config, db  # noqa: E402
from ercot.client import ErcotClient, field  # noqa: E402
from ercot.ingest import _hour_ending, _num, tracked_points  # noqa: E402
from ercot.timeutil import dam_interval_start, is_repeat_hour, rt_interval_start  # noqa: E402

log = logging.getLogger("backfill")


def day_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def backfill_dam(client: ErcotClient, day: date) -> int:
    keep = tracked_points()
    rows = []
    for raw in client.rows(config.EP_DAM_SPP, {
        "deliveryDateFrom": day.isoformat(),
        "deliveryDateTo": day.isoformat(),
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        hour = field(raw, "hourEnding", "deliveryHour")
        if price is None or hour is None:
            continue
        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        he = _hour_ending(hour)
        rows.append((point.upper(), dam_interval_start(day, he, dst_flag=repeat),
                     day, he, price, repeat, None))

    inserted, updated = db.upsert_rows(
        "dam_spp",
        ["settlement_point", "interval_start", "delivery_date", "hour_ending",
         "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "hour_ending", "dst_flag"],
    )
    log.info("dam %s: %d rows (%d new, %d changed)", day, len(rows), inserted, updated)
    return len(rows)


def backfill_rt(client: ErcotClient, day: date) -> int:
    keep = tracked_points()
    rows = []
    for raw in client.rows(config.EP_RT_SPP, {
        "deliveryDateFrom": day.isoformat(),
        "deliveryDateTo": day.isoformat(),
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        hour = field(raw, "deliveryHour", "hourEnding")
        interval = field(raw, "deliveryInterval", "intervalEnding")
        if price is None or hour is None or interval is None:
            continue
        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        he, iv = _hour_ending(hour), int(str(interval).strip())
        rows.append((point.upper(), rt_interval_start(day, he, iv, dst_flag=repeat),
                     day, he, iv, price, repeat, None))

    inserted, updated = db.upsert_rows(
        "rt_spp",
        ["settlement_point", "interval_start", "delivery_date", "delivery_hour",
         "delivery_interval", "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "delivery_hour",
                "delivery_interval", "dst_flag"],
    )
    log.info("rt %s: %d rows (%d new, %d changed)", day, len(rows), inserted, updated)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=["dam", "rt"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument(
        "--pause", type=float, default=2.0,
        help="seconds between days; the client also enforces the request limit",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        parser.error("--end is before --start")

    client = ErcotClient()
    backfill = backfill_dam if args.market == "dam" else backfill_rt

    total = 0
    for day in day_range(start, end):
        total += backfill(client, day)
        time.sleep(args.pause)

    log.info("backfill complete: %d rows across %s..%s", total, start, end)
    db.close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
