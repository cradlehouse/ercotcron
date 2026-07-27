"""Historical loads, run on the service rather than a laptop.

The database password lives only in the Render environment, so a backfill run
from a developer machine would need it copied somewhere it does not belong.
Running here keeps the credential in one place and lets a long load survive a
closed laptop.

The query shape is the inverse of the live jobs: one settlement point over a
wide date range, rather than one short window across every point. For a
20-minute live window an unfiltered request is a single call and per-point
filtering would be fifteen. Over two years that inverts — 15-minute prices are
100k rows a day unfiltered, about 15,000 requests, against 96 rows a day for one
point and a few hundred requests for the whole load.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import date, datetime, timedelta, timezone

from . import config, db
from .client import ErcotClient, field
from . import fundamentals
from .ingest import DEFAULT_POINTS, _hour_ending, _num, excluded_type, tracked_points
from .timeutil import (
    dam_interval_start,
    floor_to_5min,
    is_repeat_hour,
    parse_ercot_timestamp,
    rt_interval_start,
)

log = logging.getLogger(__name__)

# Rows per point per day, measured against the live API: dam 24, rtm 96,
# lmp5 289. Windows are sized to keep each request's page count small.
CHUNK_DAYS = {"dam": 365, "rtm": 120, "lmp5": 45, "wind": 20, "solar": 20}


def _windows(start: date, end: date, days: int):
    current = start
    while current <= end:
        stop = min(current + timedelta(days=days - 1), end)
        yield current, stop
        current = stop + timedelta(days=1)


def _load_dam(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
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


def _load_rtm(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
    rows = []
    for raw in client.rows(config.EP_RT_SPP, {
        "deliveryDateFrom": lo.isoformat(),
        "deliveryDateTo": hi.isoformat(),
        "settlementPoint": point,
    }):
        if excluded_type(raw):
            continue
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


def _load_lmp5(client: ErcotClient, point: str, lo: date, hi: date) -> tuple[int, int, int]:
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


def _load_wind(client: ErcotClient, _point: str, lo: date, hi: date) -> tuple[int, int, int]:
    r = fundamentals._renewable(client, fundamentals.WIND_EP, "wind_power",
                                fundamentals.WIND_REGIONS, fundamentals.WIND_METRICS, lo, hi)
    return r.rows_seen, r.rows_inserted, r.rows_revised


def _load_solar(client: ErcotClient, _point: str, lo: date, hi: date) -> tuple[int, int, int]:
    r = fundamentals._renewable(client, fundamentals.SOLAR_EP, "solar_power",
                                fundamentals.SOLAR_REGIONS, fundamentals.SOLAR_METRICS, lo, hi)
    return r.rows_seen, r.rows_inserted, r.rows_revised


MARKETS = {"dam": _load_dam, "rtm": _load_rtm, "lmp5": _load_lmp5,
           "wind": _load_wind, "solar": _load_solar}

# System-wide feeds have no per-point dimension; the loader ignores the point,
# so a single placeholder keeps the (points x windows) loop shape intact.
SYSTEM_MARKETS = {"wind", "solar"}

# One backfill at a time. Two concurrent loads would race the live jobs for the
# same ERCOT rate-limit budget and start drawing 429s, which is how a backfill
# turns into a live-ingest outage.
_lock = threading.Lock()
_state: dict[str, object] = {"running": False}


def status() -> dict[str, object]:
    return dict(_state)


def resolve_points(raw: str | None, market: str | None = None) -> list[str]:
    if market in SYSTEM_MARKETS:
        return ["SYSTEM"]
    if raw:
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    tracked = tracked_points()
    # '*' means every point for the live jobs; as a backfill that is a far
    # larger job, so make the caller name them.
    if tracked is None:
        raise ValueError("TRACKED_POINTS='*' — pass points explicitly for a backfill")
    return sorted(tracked or DEFAULT_POINTS)


def _run(market: str, points: list[str], start: date, end: date) -> None:
    loader = MARKETS[market]
    windows = list(_windows(start, end, CHUNK_DAYS[market]))
    total = len(points) * len(windows)
    seen = new = changed = 0
    began = time.monotonic()
    run_id = db.start_run(
        f"backfill_{market}",
        datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
    )
    client = ErcotClient()
    done = 0
    try:
        for point in points:
            for lo, hi in windows:
                s, n, c = loader(client, point, lo, hi)
                seen += s
                new += n
                changed += c
                done += 1
                _state.update(
                    progress=f"{done}/{total}", point=point, window=f"{lo}→{hi}",
                    rows_seen=seen, rows_inserted=new,
                    minutes=round((time.monotonic() - began) / 60, 1),
                )
                log.info("backfill %s %s %s→%s: %d rows (%d new)", market, point, lo, hi, s, n)
        db.finish_run(run_id, status="ok" if seen else "empty",
                      rows_seen=seen, rows_inserted=new, rows_revised=changed)
        _state.update(finished=datetime.now(timezone.utc).isoformat(), error=None)
        log.info("backfill %s done: %d rows, %d new, %.1f min",
                 market, seen, new, (time.monotonic() - began) / 60)
    except Exception as exc:  # noqa: BLE001 — a thread that raises dies silently
        log.exception("backfill %s failed", market)
        db.finish_run(run_id, status="error",
                      rows_seen=seen, rows_inserted=new, rows_revised=changed,
                      error=f"{exc}\n{traceback.format_exc()}")
        _state.update(error=str(exc), finished=datetime.now(timezone.utc).isoformat())
    finally:
        _state["running"] = False
        _lock.release()


def start(market: str, points: list[str], start_date: date, end_date: date) -> dict[str, object]:
    """Begin a backfill in the background. Raises if one is already running."""
    if market not in MARKETS:
        raise ValueError(f"unknown market: {market}")
    if start_date > end_date:
        raise ValueError("start must not be after end")
    if not _lock.acquire(blocking=False):
        raise RuntimeError(f"a backfill is already running: {_state.get('progress')}")

    windows = len(list(_windows(start_date, end_date, CHUNK_DAYS[market])))
    _state.clear()
    _state.update(running=True, market=market, points=len(points),
                  windows=windows, progress=f"0/{len(points) * windows}",
                  started=datetime.now(timezone.utc).isoformat())
    threading.Thread(
        target=_run, args=(market, points, start_date, end_date), daemon=True,
        name=f"backfill-{market}",
    ).start()
    return dict(_state)
