"""Wind, solar, load and binding constraints — why a price was what it was.

Wind and solar come back wide (one row per hour carrying every region) and
re-forecast: two years is 3.8M rows at source because each delivery hour is
predicted repeatedly before it arrives. Only the newest vintage per hour is
kept, which is what makes 105k stored rows out of 3.8M fetched.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from . import config, db
from .client import ErcotClient, field
from .ingest import Result, _num
from .timeutil import dam_interval_start, is_repeat_hour, parse_ercot_timestamp
from .ingest import _hour_ending

log = logging.getLogger(__name__)

WIND_EP = "/np4-742-cd/wpp_hrly_actual_fcast_geo"
SOLAR_EP = "/np4-745-cd/spp_hrly_actual_fcast_geo"
LOAD_EP = "/np3-561-cd/7d_load_fcast_by_wzn"
CONSTRAINT_EP = "/np6-86-cd/shdw_prices_bnd_trns_const"

# Wind and solar do not share a vocabulary: different regions and different
# forecast metric names (STWPF/WGRPP against STPPF/PVGRPP). Verified against the
# live API — assuming they matched would have silently stored nothing but nulls
# for solar, since every field lookup would have missed.
WIND_REGIONS = ["SystemWide", "Panhandle", "Coastal", "South", "West", "North"]
SOLAR_REGIONS = ["SystemWide", "CenterWest", "NorthWest", "FarWest", "SouthEast",
                 "CenterEast", "FarEast"]
WIND_METRICS = {"forecast": "STWPF", "p80": "WGRPP"}
SOLAR_METRICS = {"forecast": "STPPF", "p80": "PVGRPP"}
LOAD_ZONES = ["coast", "east", "farWest", "north", "northCentral",
              "southCentral", "southern", "west", "systemTotal"]


def _interval(raw: dict) -> tuple[datetime, date, int] | None:
    """Delivery date + hour ending → an absolute instant, or None if unmappable."""
    delivery = field(raw, "deliveryDate")
    hour = field(raw, "hourEnding")
    if delivery is None or hour is None:
        return None
    repeat = is_repeat_hour(field(raw, "DSTFlag", "dstFlag", "repeatHourFlag"))
    try:
        day = parse_ercot_timestamp(delivery).astimezone(config.CENTRAL).date()
        he = _hour_ending(hour)
        return dam_interval_start(day, he, dst_flag=repeat), day, he
    except ValueError as exc:
        log.warning("skipping unmappable hour %s HE%s — %s", delivery, hour, exc)
        return None


def _renewable(client: ErcotClient, endpoint: str, table: str,
               regions: list[str], metrics: dict[str, str],
               start: date, end: date) -> Result:
    """Wind or solar: same row shape, different regions and metric names."""
    result = Result()
    # Newest vintage wins. ERCOT returns oldest-first within a page, so a plain
    # dict assignment keeps the last seen — which is the most recently posted.
    latest: dict[tuple[datetime, str], tuple] = {}

    for raw in client.rows(endpoint, {
        "deliveryDateFrom": start.isoformat(),
        "deliveryDateTo": end.isoformat(),
    }):
        parsed = _interval(raw)
        if parsed is None:
            continue
        interval_start, day, he = parsed
        posted = field(raw, "postedDatetime", "postDatetime")
        posted_at = parse_ercot_timestamp(posted) if posted else None

        for region in regions:
            actual = _num(field(raw, f"gen{region}"))
            forecast = _num(field(raw, f"{metrics['forecast']}{region}"))
            p80 = _num(field(raw, f"{metrics['p80']}{region}"))
            cop = _num(field(raw, f"COPHSL{region}"))
            if actual is None and forecast is None and p80 is None and cop is None:
                continue
            latest[(interval_start, region)] = (
                interval_start, day, he, region, actual, forecast, p80, cop, posted_at,
            )
        result.rows_seen += 1

    inserted, updated = db.upsert_rows(
        table,
        ["interval_start", "delivery_date", "hour_ending", "region",
         "actual_mw", "forecast_mw", "forecast_p80_mw", "cop_hsl_mw", "posted_at"],
        list(latest.values()),
        conflict=["interval_start", "region"],
        update=["actual_mw", "forecast_mw", "forecast_p80_mw", "cop_hsl_mw",
                "posted_at", "delivery_date", "hour_ending"],
    )
    result.rows_inserted, result.rows_revised = inserted, updated
    log.info("%s %s→%s: %d hours, %d rows (%d new, %d changed)",
             table, start, end, result.rows_seen, len(latest), inserted, updated)
    return result


def ingest_wind(client: ErcotClient, days_back: int = 1, days_ahead: int = 7) -> Result:
    now = datetime.now(timezone.utc).astimezone(config.CENTRAL).date()
    return _renewable(client, WIND_EP, "wind_power", WIND_REGIONS, WIND_METRICS,
                      now - timedelta(days=days_back), now + timedelta(days=days_ahead))


def ingest_solar(client: ErcotClient, days_back: int = 1, days_ahead: int = 7) -> Result:
    now = datetime.now(timezone.utc).astimezone(config.CENTRAL).date()
    return _renewable(client, SOLAR_EP, "solar_power", SOLAR_REGIONS, SOLAR_METRICS,
                      now - timedelta(days=days_back), now + timedelta(days=days_ahead))


def ingest_load(client: ErcotClient, days_back: int = 1, days_ahead: int = 7) -> Result:
    now = datetime.now(timezone.utc).astimezone(config.CENTRAL).date()
    start, end = now - timedelta(days=days_back), now + timedelta(days=days_ahead)
    result = Result()
    latest: dict[tuple[datetime, str], tuple] = {}

    for raw in client.rows(LOAD_EP, {
        "deliveryDateFrom": start.isoformat(),
        "deliveryDateTo": end.isoformat(),
    }):
        parsed = _interval(raw)
        if parsed is None:
            continue
        interval_start, day, he = parsed
        posted = field(raw, "postedDatetime", "postDatetime")
        posted_at = parse_ercot_timestamp(posted) if posted else None
        for zone in LOAD_ZONES:
            mw = _num(field(raw, zone))
            if mw is None:
                continue
            latest[(interval_start, zone)] = (interval_start, day, he, zone, mw, posted_at)
        result.rows_seen += 1

    inserted, updated = db.upsert_rows(
        "load_forecast",
        ["interval_start", "delivery_date", "hour_ending", "zone",
         "forecast_mw", "posted_at"],
        list(latest.values()),
        conflict=["interval_start", "zone"],
        update=["forecast_mw", "posted_at", "delivery_date", "hour_ending"],
    )
    result.rows_inserted, result.rows_revised = inserted, updated
    log.info("load_forecast %s→%s: %d hours, %d rows (%d new)",
             start, end, result.rows_seen, len(latest), inserted)
    return result


def ingest_constraints(client: ErcotClient, since_minutes: int = 60) -> Result:
    """Binding transmission constraints and their shadow prices."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=since_minutes)
    result = Result()
    rows: dict[tuple, tuple] = {}

    def ts(moment: datetime) -> str:
        return moment.astimezone(config.CENTRAL).strftime("%Y-%m-%dT%H:%M:%S")

    for raw in client.rows(CONSTRAINT_EP, {
        "SCEDTimestampFrom": ts(start),
        "SCEDTimestampTo": ts(now),
    }):
        stamp = field(raw, "SCEDTimestamp", "scedTimestamp")
        cid = field(raw, "constraintID", "constraintId")
        contingency = field(raw, "contingencyName", "contingency")
        if stamp is None or cid is None:
            continue
        repeat = is_repeat_hour(field(raw, "repeatedHourFlag", "repeatHourFlag", "DSTFlag"))
        try:
            sced = parse_ercot_timestamp(stamp, repeated=repeat)
        except ValueError as exc:
            log.warning("constraints: skipping %s — %s", stamp, exc)
            continue
        # Contingency is part of the identity: one run can bind the same
        # constraint under several contingencies, with different shadow prices.
        key = (sced, int(cid), contingency or "")
        rows[key] = (
            sced, int(cid), contingency or "",
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
            field(raw, "CCTStatus"),
        )
        result.rows_seen += 1

    inserted, updated = db.upsert_rows(
        "binding_constraints",
        ["sced_timestamp", "constraint_id", "contingency", "constraint_name",
         "shadow_price", "max_shadow_price", "limit_mw", "value_mw", "violated_mw",
         "from_station", "to_station", "from_kv", "to_kv", "cct_status"],
        list(rows.values()),
        conflict=["sced_timestamp", "constraint_id", "contingency"],
        update=["constraint_name", "shadow_price", "max_shadow_price", "limit_mw",
                "value_mw", "violated_mw", "from_station", "to_station",
                "from_kv", "to_kv", "cct_status"],
    )
    result.rows_inserted, result.rows_revised = inserted, updated
    log.info("binding_constraints: %d rows (%d new, %d changed)",
             result.rows_seen, inserted, updated)
    return result
