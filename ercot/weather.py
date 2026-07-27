"""Independent weather forecasts from Open-Meteo.

ERCOT publishes a wind forecast but no measure of its own confidence. Running
three global models over the same hours supplies that: when ECMWF, GFS and ICON
disagree, the atmosphere is genuinely uncertain — and generation, and therefore
price, is uncertain with it.

Free and unauthenticated, and on a different host from ERCOT, so this shares no
rate-limit budget with the price feeds and can run while a backfill does.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone

import httpx

from . import config, db
from .ingest import Result

log = logging.getLogger(__name__)

API = "https://api.open-meteo.com/v1/forecast"
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
TIMEOUT = httpx.Timeout(120.0, connect=30.0)

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


def ingest_weather(_client: object = None, past_days: int = 2,
                   forecast_days: int = 7) -> Result:
    """Fetch every model for every region and store the per-site mean.

    Takes and ignores an ErcotClient so it matches the Job signature — this
    source needs no ERCOT auth and must not consume its rate limit.
    """
    result = Result()
    rows: dict[tuple, tuple] = {}

    for region, sites in SITES.items():
        per_model: dict[str, dict[str, list[float]]] = {m: {} for m in MODELS}
        for lat, lon in sites:
            try:
                hourly = _fetch_site(lat, lon, past_days, forecast_days)
            except Exception as exc:  # noqa: BLE001 — one bad site must not lose the region
                log.warning("open-meteo %s (%s,%s) failed: %s", region, lat, lon, exc)
                continue
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
                moment = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
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
    log.info("weather: %d regions, %d rows (%d new, %d changed)",
             len(SITES), len(rows), inserted, updated)
    return result
