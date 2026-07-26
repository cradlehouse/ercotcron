"""Ingest jobs.

One query per report, filtered in Python. Ingest never loops per settlement
point: ERCOT allows 30 requests a minute and additionally throttles on
unpublished data-volume thresholds, so per-point looping would be over a
thousand requests a job at full coverage instead of one to three. Do not
reintroduce the loop.

Look-back windows are deliberately tight — the five-minute job pulls twenty
minutes, with an hourly repair pass covering three hours. Re-pulling a whole day
every five minutes is the volume pattern that gets subscriptions flagged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import config, db
from .client import ErcotClient, field
from .timeutil import (
    central_date,
    dam_interval_start,
    floor_to_5min,
    is_repeat_hour,
    parse_ercot_timestamp,
    rt_interval_start,
)

log = logging.getLogger(__name__)

# Storing every node would be roughly 105M five-minute rows a year, well past
# what the Postgres tier is sized for. Track hubs and load zones by default and
# widen deliberately.
DEFAULT_POINTS = [
    "HB_BUSAVG", "HB_HUBAVG", "HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_PAN",
    "LZ_AEN", "LZ_CPS", "LZ_HOUSTON", "LZ_LCRA", "LZ_NORTH", "LZ_RAYBN", "LZ_SOUTH", "LZ_WEST",
]


def tracked_points() -> set[str] | None:
    """None means keep every point the report returns."""
    raw = os.environ.get("TRACKED_POINTS", "")
    if raw.strip() == "*":
        return None
    names = [p.strip().upper() for p in raw.split(",") if p.strip()]
    return set(names or DEFAULT_POINTS)


@dataclass
class Result:
    rows_seen: int = 0
    rows_inserted: int = 0
    rows_revised: int = 0
    requests: int = 0

    @property
    def status(self) -> str:
        return "ok" if self.rows_seen else "empty"


def _ts(moment: datetime) -> str:
    return moment.astimezone(config.CENTRAL).strftime("%Y-%m-%dT%H:%M:%S")


def _date(moment: datetime) -> str:
    return central_date(moment).isoformat()


def _num(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- day-ahead --


def ingest_dam(client: ErcotClient, days_ahead: int = 1) -> Result:
    """Day-ahead settlement point prices for today and tomorrow."""
    keep = tracked_points()
    now = datetime.now(timezone.utc)
    start = _date(now)
    end = _date(now + timedelta(days=days_ahead))

    result = Result()
    rows: list[tuple] = []
    for raw in client.rows(config.EP_DAM_SPP, {
        "deliveryDateFrom": start,
        "deliveryDateTo": end,
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        delivery = field(raw, "deliveryDate")
        hour_ending = field(raw, "hourEnding", "deliveryHour")
        if price is None or delivery is None or hour_ending is None:
            continue

        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        hour = _hour_ending(hour_ending)
        try:
            day = parse_ercot_timestamp(delivery).astimezone(config.CENTRAL).date()
            interval_start = dam_interval_start(day, hour, dst_flag=repeat)
        except ValueError as exc:
            log.warning("dam: skipping unmappable row %s HE%s — %s", point, hour_ending, exc)
            continue
        posted = field(raw, "postDatetime", "postedDatetime", "postDateTime")

        rows.append((
            point.upper(), interval_start, day, hour, price, repeat,
            parse_ercot_timestamp(posted) if posted else None,
        ))
        result.rows_seen += 1

    result.rows_inserted, result.rows_revised = db.upsert_rows(
        "dam_spp",
        ["settlement_point", "interval_start", "delivery_date", "hour_ending",
         "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "hour_ending", "dst_flag"],
    )
    return result


def _hour_ending(value: object) -> int:
    """Hour ending arrives as 1, '01', '01:00' or '0100' depending on the report."""
    text = str(value).strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    elif len(text) == 4 and text.isdigit():
        text = text[:2]
    return int(text)


# ------------------------------------------------------- real-time 15-min --


def ingest_rtm(client: ErcotClient) -> Result:
    """Settled 15-minute SPP for the current operating day."""
    keep = tracked_points()
    now = datetime.now(timezone.utc)
    day = _date(now)

    result = Result()
    rows: list[tuple] = []
    for raw in client.rows(config.EP_RT_SPP, {
        "deliveryDateFrom": day,
        "deliveryDateTo": day,
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "settlementPointPrice", "spp", "price"))
        delivery = field(raw, "deliveryDate")
        hour = field(raw, "deliveryHour", "hourEnding")
        interval = field(raw, "deliveryInterval", "intervalEnding")
        if price is None or delivery is None or hour is None or interval is None:
            continue

        repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
        try:
            day_value = parse_ercot_timestamp(delivery).astimezone(config.CENTRAL).date()
            hour_value = _hour_ending(hour)
            interval_value = int(str(interval).strip())
            interval_start = rt_interval_start(
                day_value, hour_value, interval_value, dst_flag=repeat
            )
        except ValueError as exc:
            log.warning("rtm: skipping unmappable row %s HE%s — %s", point, hour, exc)
            continue
        posted = field(raw, "postDatetime", "postedDatetime", "postDateTime")

        rows.append((
            point.upper(), interval_start, day_value, hour_value, interval_value,
            price, repeat, parse_ercot_timestamp(posted) if posted else None,
        ))
        result.rows_seen += 1

    result.rows_inserted, result.rows_revised = db.upsert_rows(
        "rt_spp",
        ["settlement_point", "interval_start", "delivery_date", "delivery_hour",
         "delivery_interval", "price", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "posted_at", "delivery_date", "delivery_hour",
                "delivery_interval", "dst_flag"],
    )
    return result


# --------------------------------------------------- five-minute SCED LMP --

# UNVERIFIED: the SCED and RTD parameter names below were written from ERCOT's
# naming pattern, not read from the published spec. A wrong name does not raise —
# it returns zero rows, which is why every job records status 'empty' separately
# from 'ok'. Confirm with:
#   python scripts/describe_endpoint.py /np6-788-cd/lmp_node_zone_hub
#   python scripts/describe_endpoint.py /np6-970-cd/rtd_lmp_node_zone_hub


def ingest_lmp5(client: ErcotClient, since_minutes: int = 20) -> Result:
    """Five-minute SCED LMP for the recent window."""
    keep = tracked_points()
    now = datetime.now(timezone.utc)
    start = floor_to_5min(now - timedelta(minutes=since_minutes))

    result = Result()
    rows: list[tuple] = []
    for raw in client.rows(config.EP_LMP_5MIN, {
        "SCEDTimestampFrom": _ts(start),
        "SCEDTimestampTo": _ts(now),
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "LMP", "lmp", "settlementPointPrice", "price"))
        stamp = field(raw, "SCEDTimestamp", "scedTimestamp", "RTDTimestamp", "timestamp")
        if price is None or stamp is None:
            continue

        repeat = is_repeat_hour(field(raw, "repeatHourFlag", "DSTFlag", "dstFlag"))
        try:
            sced_timestamp = parse_ercot_timestamp(stamp, repeated=repeat)
        except ValueError as exc:
            log.warning("lmp5: skipping unmappable row %s %s — %s", point, stamp, exc)
            continue
        interval_start = floor_to_5min(sced_timestamp)

        rows.append((
            point.upper(), interval_start, sced_timestamp, price,
            _num(field(raw, "energyComponent", "energy")),
            _num(field(raw, "congestionComponent", "congestion")),
            _num(field(raw, "lossComponent", "loss")),
            repeat, None,
        ))
        result.rows_seen += 1

    result.rows_inserted, result.rows_revised = db.upsert_rows(
        "rt_lmp_5min",
        ["settlement_point", "interval_start", "sced_timestamp", "price",
         "energy", "congestion", "loss", "dst_flag", "posted_at"],
        rows,
        conflict=["settlement_point", "interval_start"],
        update=["price", "sced_timestamp", "energy", "congestion", "loss", "dst_flag"],
    )
    return result


def ingest_rtd(client: ErcotClient, since_minutes: int = 15) -> Result:
    """RTD indicative LMP. Every run time is its own forecast vintage."""
    keep = tracked_points()
    now = datetime.now(timezone.utc)
    start = floor_to_5min(now - timedelta(minutes=since_minutes))

    result = Result()
    rows: list[tuple] = []
    for raw in client.rows(config.EP_RTD_LMP, {
        "RTDTimestampFrom": _ts(start),
        "RTDTimestampTo": _ts(now),
    }):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point or (keep is not None and point.upper() not in keep):
            continue
        price = _num(field(raw, "LMP", "lmp", "price"))
        run = field(raw, "RTDTimestamp", "rtdTimestamp", "timestamp")
        target = field(raw, "intervalEnding", "intervalEndingTime", "SCEDTimestamp")
        if price is None or run is None or target is None:
            continue

        repeat = is_repeat_hour(field(raw, "repeatHourFlag", "DSTFlag", "dstFlag"))
        try:
            rtd_timestamp = parse_ercot_timestamp(run, repeated=repeat)
            # intervalEnding names the close of the target interval.
            interval_start = floor_to_5min(
                parse_ercot_timestamp(target, repeated=repeat) - timedelta(minutes=5)
            )
        except ValueError as exc:
            log.warning("rtd: skipping unmappable row %s %s — %s", point, run, exc)
            continue

        rows.append((
            point.upper(), interval_start, rtd_timestamp, price,
            _num(field(raw, "energyComponent", "energy")),
            _num(field(raw, "congestionComponent", "congestion")),
            _num(field(raw, "lossComponent", "loss")),
            repeat,
        ))
        result.rows_seen += 1

    result.rows_inserted = db.insert_rows_ignore_dupes(
        "rtd_lmp",
        ["settlement_point", "interval_start", "rtd_timestamp", "price",
         "energy", "congestion", "loss", "dst_flag"],
        rows,
        conflict=["settlement_point", "interval_start", "rtd_timestamp"],
    )
    return result


# ------------------------------------------------------------- catalogue --


def ingest_points(client: ErcotClient) -> Result:
    """Refresh the settlement point catalogue from yesterday's RT report.

    Derived from a report we already read rather than a separate catalogue
    endpoint, so it needs no additional subscription or parameter guesswork.
    """
    now = datetime.now(timezone.utc)
    day = _date(now - timedelta(days=1))

    seen: dict[str, tuple[str, str | None, str | None]] = {}
    for raw in client.rows(config.EP_RT_SPP, {"deliveryDateFrom": day, "deliveryDateTo": day}):
        point = field(raw, "settlementPoint", "settlementPointName")
        if not point:
            continue
        name = point.upper()
        if name in seen:
            continue
        seen[name] = (
            name,
            field(raw, "settlementPointType", "settlementPointTypeName"),
            field(raw, "zone", "loadZone"),
        )

    written = db.upsert_settlement_points(seen.values())
    return Result(rows_seen=len(seen), rows_inserted=written)


def maintain_partitions(_client: ErcotClient | None = None) -> Result:
    created = db.ensure_partitions(months_ahead=3)
    stray = db.default_partition_rows()
    for table, count in stray.items():
        if count:
            log.warning("%s holds %d rows — partition maintenance has been failing", table, count)
    return Result(rows_seen=len(created), rows_inserted=len(created))
