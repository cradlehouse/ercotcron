"""Job registry and the wrapper that runs one, records it, and pings a heartbeat."""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx

from . import config, crr, db, fundamentals, ingest, weather
from .client import ErcotClient
from .ingest import Result

log = logging.getLogger(__name__)

_client: ErcotClient | None = None


def client() -> ErcotClient:
    """One client per process: the bearer token is cached across every job.

    Six separate cron containers would each re-authenticate on every tick — for
    the five-minute job alone that is roughly 288 needless token requests a day.
    """
    global _client
    if _client is None:
        _client = ErcotClient()
    return _client


@dataclass(frozen=True)
class Job:
    name: str
    run: Callable[[ErcotClient], Result]
    description: str
    # Chicago-local cron fields. ERCOT publishes on a Central clock, so a job
    # pinned to a wall-clock hour must be scheduled in Central or it drifts an
    # hour at each DST transition.
    trigger: dict[str, str]
    timezone: str = "America/Chicago"


def _refresh_signals() -> ingest.Result:
    timings = db.refresh_signal_views()
    result = ingest.Result()
    result.rows_seen = len(timings)
    log.info("signal views refreshed: %s", timings)
    return result


JOBS: dict[str, Job] = {
    "lmp5": Job(
        name="lmp5",
        run=lambda c: ingest.ingest_lmp5(c, since_minutes=20),
        description="5-minute SCED LMP, last 20 minutes",
        trigger={"minute": "0-59/5"},
    ),
    "rtd": Job(
        name="rtd",
        run=lambda c: ingest.ingest_rtd(c, since_minutes=15),
        description="RTD forecast vintages, last 15 minutes",
        trigger={"minute": "2-59/5"},
    ),
    "constraints": Job(
        name="constraints",
        # A 60-minute lookback on a 10-minute cadence, so runs overlap heavily.
        # Constraints only exist while something is actually congested — at 6am
        # a 20-minute window is legitimately empty, and a job that reports
        # 'empty' most nights teaches you to ignore the one night it matters.
        run=lambda c: fundamentals.ingest_constraints(c, since_minutes=60),
        description="Binding transmission constraints and shadow prices",
        trigger={"minute": "6-59/10"},
    ),
    "wind": Job(
        name="wind",
        # Forecasts post near the top of the hour; :20 avoids racing publication.
        run=lambda c: fundamentals.ingest_wind(c),
        description="Regional wind actual and forecast, 8-day window",
        trigger={"minute": "20"},
    ),
    "solar": Job(
        name="solar",
        run=lambda c: fundamentals.ingest_solar(c),
        description="Regional solar actual and forecast, 8-day window",
        trigger={"minute": "24"},
    ),
    "load_fcast": Job(
        name="load_fcast",
        run=lambda c: fundamentals.ingest_load(c),
        description="Seven-day load forecast by weather zone",
        trigger={"minute": "28"},
    ),
    "signals": Job(
        name="signals",
        # Hourly, offset from everything else. The scanner reads these
        # materialised views; without the refresh they silently go stale, which
        # on a monitoring page is worse than being slow.
        run=lambda c: _refresh_signals(),
        description="Rebuild scanner materialised views",
        trigger={"minute": "34"},
    ),
    "weather": Job(
        name="weather",
        # Open-Meteo, not ERCOT: no shared auth and no shared rate limit, so
        # this is safe to run alongside a price backfill. Hourly is plenty —
        # the global models only produce new runs every 6 hours.
        run=lambda c: weather.ingest_weather(c),
        description="Independent wind forecasts (ECMWF/GFS/ICON) by region",
        trigger={"minute": "42"},
    ),
    "crr": Job(
        name="crr",
        # Monthly auctions clear once a month, so a daily check is generous;
        # it is cheap because an already-loaded auction upserts to no changes.
        run=lambda c: crr.ingest_job(c, limit=2),
        description="CRR auction results, newest 2 monthly auctions",
        trigger={"hour": "8", "minute": "40"},
    ),
    "rtm": Job(
        name="rtm",
        run=lambda c: ingest.ingest_rtm(c),
        description="Settled 15-minute SPP, current operating day",
        trigger={"minute": "4,19,34,49"},
    ),
    "lmp5_catchup": Job(
        name="lmp5_catchup",
        run=lambda c: ingest.ingest_lmp5(c, since_minutes=180),
        description="5-minute repair pass, last 3 hours",
        trigger={"minute": "8"},
    ),
    "dam": Job(
        name="dam",
        run=lambda c: ingest.ingest_dam(c, days_ahead=1),
        description="Day-ahead SPP, today and tomorrow",
        trigger={"hour": "11,18", "minute": "47"},
    ),
    "points": Job(
        name="points",
        run=lambda c: ingest.ingest_points(c),
        description="Settlement point catalogue refresh",
        trigger={"day_of_week": "mon", "hour": "9", "minute": "0"},
    ),
    "partitions": Job(
        name="partitions",
        run=lambda c: ingest.maintain_partitions(c),
        description="Create monthly partitions three months ahead",
        trigger={"hour": "3", "minute": "10"},
    ),
}


def _heartbeat(job: str, ok: bool) -> None:
    url = config.heartbeat_url(job)
    if not url:
        return
    try:
        httpx.post(url if ok else f"{url.rstrip('/')}/fail", timeout=10.0)
    except httpx.HTTPError as exc:
        # A monitoring failure must never take down an ingest run.
        log.warning("heartbeat for %s failed: %s", job, exc)


def run_job(name: str) -> dict[str, object]:
    """Run one job, record it in ingest_runs, and never raise.

    The scheduler shares a process with every other job; an exception that
    escaped here would take the whole service down.
    """
    job = JOBS.get(name)
    if job is None:
        raise KeyError(f"unknown job: {name}")

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    run_id = db.start_run(job.name, now - timedelta(hours=1), now)
    log.info("job %s starting", job.name)

    try:
        result = job.run(client())
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
        log.exception("job %s failed", job.name)
        db.finish_run(run_id, status="error", error=f"{exc}\n{traceback.format_exc()}")
        _heartbeat(job.name, ok=False)
        return {"job": job.name, "status": "error", "error": str(exc)}

    db.finish_run(
        run_id,
        status=result.status,
        requests=result.requests,
        rows_seen=result.rows_seen,
        rows_inserted=result.rows_inserted,
        rows_revised=result.rows_revised,
    )

    if result.status == "empty":
        # Not an exception, but the signature of a wrong query parameter name.
        log.warning("job %s returned zero rows — check the endpoint parameters", job.name)

    _heartbeat(job.name, ok=result.status == "ok")
    log.info(
        "job %s %s in %.1fs — seen=%d inserted=%d revised=%d",
        job.name, result.status, time.monotonic() - started,
        result.rows_seen, result.rows_inserted, result.rows_revised,
    )
    return {
        "job": job.name,
        "status": result.status,
        "rows_seen": result.rows_seen,
        "rows_inserted": result.rows_inserted,
        "rows_revised": result.rows_revised,
        "seconds": round(time.monotonic() - started, 2),
    }
