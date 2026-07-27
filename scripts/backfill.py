#!/usr/bin/env python3
"""Historical loads. Run locally, not on a schedule.

This is also the disaster recovery plan: every price is reconstructible from
ERCOT, which is why the Supabase point-in-time-recovery add-on is not worth
$100/mo here. What backfill cannot reconstruct is the *revision* timeline —
posted_at, price_from and forecast vintages are only observable live.

    python scripts/backfill.py --market rtm --start 2024-07-01 --end 2026-07-26
    python scripts/backfill.py --market dam --start 2024-07-01 --end 2026-07-26
    python scripts/backfill.py --market lmp5 --start 2026-01-01 --end 2026-07-26

Queries one settlement point over a wide date range, rather than one day across
every point. The live jobs do the opposite deliberately — for a 20-minute window
an unfiltered request is a single call, where per-point filtering would be
fifteen — but over years that inverts. Two years of 15-minute prices is 100k
rows a day unfiltered, roughly 15,000 requests; the same span filtered to one
point is 96 rows a day, and the whole backfill is a few hundred requests.
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
from ercot.ingest import DEFAULT_POINTS, _hour_ending, _num, tracked_points  # noqa: E402
from ercot.timeutil import (  # noqa: E402
    dam_interval_start,
    floor_to_5min,
    is_repeat_hour,
    parse_ercot_timestamp,
    rt_interval_start,
)

log = logging.getLogger("backfill")


def chunks(start: date, end: date, days: int):
    """Inclusive date windows of at most `days`."""
    current = start
    while current <= end:
        stop = min(current + timedelta(days=days - 1), end)
        yield current, stop
        current = stop + timedelta(days=1)


# ----------------------------------------------------------------- markets --


def load_dam(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
    rows = []
    for raw in client.rows(config.EP_DAM_SPP, {
        "deliveryDateFrom": lo.isoformat(),
        "deliveryDateTo": hi.isoformat(),
        "settlementPoint": point,
    }):
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        delivery = field(raw, "deliveryDate")
        hour = field(raw, "hourEnding", "deliveryHour")
        if price is None or delivery is None or hour is None:
            continue
        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        try:
            day = parse_ercot_timestamp(delivery).astimezone(config.CENTRAL).date()
            he = _hour_ending(hour)
            start = dam_interval_start(day, he, dst_flag=repeat)
        except ValueError as exc:
            log.warning("dam: skipping %s %s HE%s — %s", point, delivery, hour, exc)
            continue
        rows.append((point, start, day, he, price, repeat, None))

    inserted, updated = db.upsert_rows(
        "dam_spp",
        ["settlement_point", "interval_start", "delivery_date", "hour_ending",
         "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "hour_ending", "dst_flag"],
    )
    return len(rows), inserted, updated


def load_rtm(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
    rows = []
    for raw in client.rows(config.EP_RT_SPP, {
        "deliveryDateFrom": lo.isoformat(),
        "deliveryDateTo": hi.isoformat(),
        "settlementPoint": point,
    }):
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        delivery = field(raw, "deliveryDate")
        hour = field(raw, "deliveryHour", "hourEnding")
        interval = field(raw, "deliveryInterval", "intervalEnding")
        if price is None or delivery is None or hour is None or interval is None:
            continue
        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        try:
            day = parse_ercot_timestamp(delivery).astimezone(config.CENTRAL).date()
            he = _hour_ending(hour)
            iv = int(str(interval).strip())
            start = rt_interval_start(day, he, iv, dst_flag=repeat)
        except ValueError as exc:
            log.warning("rtm: skipping %s %s HE%s — %s", point, delivery, hour, exc)
            continue
        rows.append((point, start, day, he, iv, price, repeat, None))

    inserted, updated = db.upsert_rows(
        "rt_spp",
        ["settlement_point", "interval_start", "delivery_date", "delivery_hour",
         "delivery_interval", "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "delivery_hour",
                "delivery_interval", "dst_flag"],
    )
    return len(rows), inserted, updated


def load_lmp5(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
    rows = []
    for raw in client.rows(config.EP_LMP_5MIN, {
        "SCEDTimestampFrom": f"{lo.isoformat()}T00:00:00",
        "SCEDTimestampTo": f"{hi.isoformat()}T23:59:59",
        "settlementPoint": point,
    }):
        price = _num(field(raw, "LMP", "lmp", "settlementPointPrice", "price"))
        stamp = field(raw, "SCEDTimestamp", "scedTimestamp", "timestamp")
        if price is None or stamp is None:
            continue
        repeat = is_repeat_hour(field(raw, "repeatHourFlag", "DSTFlag", "dstFlag"))
        try:
            sced = parse_ercot_timestamp(stamp, repeated=repeat)
        except ValueError as exc:
            log.warning("lmp5: skipping %s %s — %s", point, stamp, exc)
            continue
        rows.append((
            point, floor_to_5min(sced), sced, price,
            _num(field(raw, "energyComponent", "energy")),
            _num(field(raw, "congestionComponent", "congestion")),
            _num(field(raw, "lossComponent", "loss")),
            repeat, None,
        ))

    inserted, updated = db.upsert_rows(
        "rt_lmp_5min",
        ["settlement_point", "interval_start", "sced_timestamp", "price",
         "energy", "congestion", "loss", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "sced_timestamp", "energy", "congestion", "loss",
                "dst_flag", "posted_at"],
    )
    return len(rows), inserted, updated


MARKETS = {"dam": load_dam, "rtm": load_rtm, "lmp5": load_lmp5}
# Chunk sizes keep each request's page count small. Rows per point per day:
# dam 24, rtm 96, lmp5 289.
CHUNK_DAYS = {"dam": 365, "rtm": 120, "lmp5": 45}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(MARKETS), required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    parser.add_argument("--points", help="comma-separated; defaults to TRACKED_POINTS")
    parser.add_argument("--chunk-days", type=int, default=None)
    parser.add_argument("--pause", type=float, default=0.0,
                        help="extra seconds between chunks; the client already paces requests")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if start > end:
        raise SystemExit("--start must not be after --end")

    if args.points:
        points = [p.strip().upper() for p in args.points.split(",") if p.strip()]
    else:
        tracked = tracked_points()
        # '*' means every point live; for a backfill that is a different and much
        # larger job, so require the caller to name them explicitly.
        if tracked is None:
            raise SystemExit("TRACKED_POINTS='*' — pass --points explicitly for a backfill")
        points = sorted(tracked or DEFAULT_POINTS)

    loader = MARKETS[args.market]
    span = args.chunk_days or CHUNK_DAYS[args.market]
    windows = list(chunks(start, end, span))
    total_seen = total_new = total_changed = 0
    started = time.monotonic()

    log.info("%s: %d points × %d windows, %s → %s",
             args.market, len(points), len(windows), start, end)

    for pi, point in enumerate(points, 1):
        for lo, hi in windows:
            seen, new, changed = loader(client_singleton(), point, lo, hi)
            total_seen += seen
            total_new += new
            total_changed += changed
            log.info("[%d/%d] %s %s→%s: %d rows (%d new, %d changed)",
                     pi, len(points), point, lo, hi, seen, new, changed)
            if args.pause:
                time.sleep(args.pause)

    log.info("done in %.1f min: %d rows seen, %d new, %d changed",
             (time.monotonic() - started) / 60, total_seen, total_new, total_changed)
    return 0


_CLIENT: ErcotClient | None = None


def client_singleton() -> ErcotClient:
    """One client for the whole run, so the token and rate limiter are shared."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = ErcotClient()
    return _CLIENT


if __name__ == "__main__":
    raise SystemExit(main())
