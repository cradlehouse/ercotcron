"""Independent weather forecasts from Open-Meteo.

ERCOT publishes a wind forecast but no measure of its own confidence. Running
three global models over the same hours supplies that: when ECMWF, GFS and ICON
disagree, the atmosphere is genuinely uncertain — and generation, and therefore
price, is uncertain with it.

Free and unauthenticated, and on a different host from ERCOT, so this shares no
rate-limit budget with the price feeds and can run while a backfill does.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import statistics
from datetime import UTC, datetime, timedelta

import httpx

from . import db
from .ingest import Result

log = logging.getLogger(__name__)

API = "https://api.open-meteo.com/v1/forecast"
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
TIMEOUT = httpx.Timeout(120.0, connect=30.0)
META = "https://api.open-meteo.com/data/{model}/static/meta.json"

# The seamless blends publish no run metadata of their own; their global
# component does. Recorded as a labelled reference, not as the blend's run.
META_MODEL = {
    "ecmwf_ifs025": "ecmwf_ifs025",
    "gfs_seamless": "ncep_gfs013",
    "icon_seamless": "dwd_icon",
}

# Representative sites per ERCOT wind region, chosen near the actual wind farm
# clusters rather than at region centroids — a centroid of the Panhandle is
# mostly empty ranchland and forecasts nothing that generates.
SITES: dict[str, list[tuple[float, float]]] = {
    "Panhandle": [(35.22, -101.83), (35.55, -101.05), (34.98, -101.92)],
    "West":      [(32.45, -100.40), (31.95, -101.45), (32.75, -101.00)],
    "South":     [(27.75, -97.80), (26.95, -97.75), (28.35, -98.20)],
    "Coastal":   [(28.80, -96.20), (27.60, -97.35)],
    "North":     [(33.85, -99.20), (34.15, -98.40)],
}


def _fetch_site(lat: float, lon: float, past_days: int, forecast_days: int) -> dict:
    resp = httpx.get(API, params={
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_100m",
        "models": ",".join(MODELS),
        "past_days": past_days, "forecast_days": forecast_days,
        "timezone": "UTC",
    }, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("hourly", {})


def _run_meta(model: str) -> tuple[datetime | None, datetime | None, str | None]:
    """(initialisation, availability, source model) of the latest run, or Nones."""
    source = META_MODEL.get(model)
    if source is None:
        return None, None, None
    try:
        resp = httpx.get(META.format(model=source), timeout=TIMEOUT)
        resp.raise_for_status()
        meta = resp.json()
    except Exception as exc:
        log.warning("open-meteo meta %s failed: %s", source, exc)
        return None, None, None

    def stamp(key: str) -> datetime | None:
        value = meta.get(key)
        return datetime.fromtimestamp(value, UTC) if isinstance(value, (int, float)) else None

    return stamp("last_run_initialisation_time"), stamp("last_run_availability_time"), source


def vintage_rows(region: str, lat: float, lon: float, hourly: dict,
                 seen_at: datetime, meta: dict) -> list[tuple]:
    """One row per model: the forecast series from the fetch hour onward.

    Hours before the fetch are dropped — past_days returns stitched
    near-analysis values, not a forecast anyone could have acted on.
    """
    floor = seen_at.replace(minute=0, second=0, microsecond=0)
    times = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly.get("time") or []]
    rows = []
    for model in MODELS:
        series = hourly.get(f"wind_speed_100m_{model}")
        if not series:
            continue
        pairs = [(t, v) for t, v in zip(times, series) if t >= floor]
        if not pairs or all(v is None for _, v in pairs):
            continue
        # the API returns a contiguous hourly grid; refuse anything else
        # rather than store an array whose positions mean the wrong hours
        if any(b[0] - a[0] != timedelta(hours=1) for a, b in itertools.pairwise(pairs)):
            log.warning("open-meteo %s %s (%s,%s): non-hourly grid, vintage skipped",
                        model, region, lat, lon)
            continue
        start = pairs[0][0]
        vals = [None if v is None else float(v) for _, v in pairs]
        digest = hashlib.sha256(json.dumps(
            [start.isoformat(), 3600, vals], separators=(",", ":")).encode()).hexdigest()
        init, avail, source = meta.get(model, (None, None, None))
        rows.append((f"{region}:{lat},{lon}", region, lat, lon, model, start, vals,
                     digest, seen_at, init, avail, source))
    return rows


VINTAGE_COLUMNS = ["site_id", "region", "lat", "lon", "model", "valid_start", "vals",
                   "series_sha256", "first_seen_at", "ref_run_init",
                   "ref_run_available", "run_meta_source"]


def ingest_weather(_client: object = None, past_days: int = 2,
                   forecast_days: int = 7) -> Result:
    """Fetch every model for every region and store the per-site mean.

    Takes and ignores an ErcotClient so it matches the Job signature — this
    source needs no ERCOT auth and must not consume its rate limit.
    """
    result = Result()
    rows: dict[tuple, tuple] = {}
    vintages: list[tuple] = []
    seen_at = datetime.now(UTC)
    meta = {m: _run_meta(m) for m in MODELS}

    for region, sites in SITES.items():
        per_model: dict[str, dict[str, list[float]]] = {m: {} for m in MODELS}
        for lat, lon in sites:
            try:
                hourly = _fetch_site(lat, lon, past_days, forecast_days)
            except Exception as exc:
                log.warning("open-meteo %s (%s,%s) failed: %s", region, lat, lon, exc)
                continue
            vintages.extend(vintage_rows(region, lat, lon, hourly, seen_at, meta))
            times = hourly.get("time") or []
            for model in MODELS:
                series = hourly.get(f"wind_speed_100m_{model}")
                if not series:
                    continue
                for stamp, value in zip(times, series):
                    if value is not None:
                        per_model[model].setdefault(stamp, []).append(float(value))

        for model, by_time in per_model.items():
            for stamp, values in by_time.items():
                # Require every site to have reported, so a region's mean is not
                # silently redefined hour to hour by which sites responded.
                if len(values) != len(sites):
                    continue
                moment = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
                rows[(moment, region, model)] = (
                    moment, region, model, round(statistics.mean(values), 2),
                )
                result.rows_seen += 1

    inserted, updated = db.upsert_rows(
        "weather_forecast",
        ["interval_start", "region", "model", "wind_speed_100m"],
        list(rows.values()),
        conflict=["interval_start", "region", "model"],
        update=["wind_speed_100m"],
    )
    result.rows_inserted, result.rows_revised = inserted, updated
    # The archive is written after the latest-value table so a failure here
    # can never stop the live consumers; it is logged, not swallowed.
    try:
        archived = db.insert_rows_ignore_dupes(
            "weather_forecast_vintages", VINTAGE_COLUMNS, vintages,
            conflict=["site_id", "model", "variable", "valid_start", "series_sha256"])
    except Exception as exc:
        archived = 0
        log.error("weather vintages: archive write failed: %s", exc)
    log.info("weather: %d regions, %d rows (%d new, %d changed); %d/%d vintages archived",
             len(SITES), len(rows), inserted, updated, archived, len(vintages))
    return result
