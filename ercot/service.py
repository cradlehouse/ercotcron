"""The Render service: in-process scheduler plus a small operational API.

One long-lived process runs every schedule, which is what makes the shared
bearer token, the shared rate limiter and `max_instances=1` overlap protection
possible. Scheduling deliberately does not live on Vercel — a `crons` block
there would double every pull and burn the ERCOT rate limit.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Header, HTTPException

from . import backfill as backfill_mod, config, db
from .jobs import JOBS, run_job

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("ercotcron")

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(4)},
    job_defaults={
        # No two runs of the same job may overlap, and a run delayed past its
        # next slot is dropped rather than queued into a burst.
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 120,
    },
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("SCHEDULER_ENABLED", "true").lower() != "false":
        for job in JOBS.values():
            scheduler.add_job(
                run_job,
                CronTrigger(**job.trigger, timezone=job.timezone),
                args=[job.name],
                id=job.name,
                name=job.description,
                replace_existing=True,
            )
        scheduler.start()
        log.info("scheduler started with %d jobs", len(JOBS))

        try:
            created = db.ensure_partitions(months_ahead=3)
            log.info("partitions verified: %d", len(created))
        except Exception as exc:  # noqa: BLE001 — startup must not be fatal
            log.warning("partition check failed at startup: %s", exc)
    else:
        log.warning("SCHEDULER_ENABLED=false — API only, nothing will be ingested")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)
    db.close_pool()


app = FastAPI(title="ercotcron", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness plus the two things that actually break: DB and credentials."""
    checks = {
        "database": False,
        "ercot_credentials": all(
            os.environ.get(k) for k in
            ("ERCOT_USERNAME", "ERCOT_PASSWORD", "ERCOT_SUBSCRIPTION_KEY")
        ),
        "scheduler": scheduler.running,
    }
    try:
        checks["database"] = db.ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("health check database probe failed: %s", exc)

    healthy = checks["database"] and checks["ercot_credentials"]
    return {"ok": healthy, "checks": checks, "jobs": sorted(JOBS)}


@app.get("/runs")
def runs(limit: int = 20) -> dict[str, object]:
    """Recent ingest runs.

    Reports a database failure as a message rather than a bare 500. This is the
    endpoint reached for when something is already wrong, and an unexplained
    500 here sends you looking for a bug in the service when the real answer is
    usually an unset or malformed DATABASE_URL.
    """
    try:
        return {"runs": db.recent_runs(min(limit, 200))}
    except Exception as exc:  # noqa: BLE001
        log.warning("/runs database read failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"cannot read ingest_runs — check DATABASE_URL: {exc}",
        ) from exc


@app.get("/schedule")
def schedule() -> dict[str, object]:
    return {
        "jobs": [
            {
                "job": j.id,
                "description": j.name,
                "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
            }
            for j in scheduler.get_jobs()
        ]
    }


@app.post("/trigger/{job_name}")
def trigger(job_name: str, x_trigger_secret: str = Header(default="")) -> dict[str, object]:
    """Manual run. Guarded because it can spend ERCOT rate-limit budget."""
    secret = config.trigger_secret()
    if not secret or x_trigger_secret != secret:
        raise HTTPException(status_code=401, detail="invalid trigger secret")
    if job_name not in JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job: {job_name}")
    return run_job(job_name)


@app.get("/stats")
def stats() -> dict[str, object]:
    """Row counts and database size — the guard rail before a large backfill."""
    try:
        return db.table_stats()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"cannot read table stats: {exc}") from exc


@app.get("/backfill")
def backfill_status() -> dict[str, object]:
    return backfill_mod.status()


@app.post("/backfill/{market}")
def backfill_start(
    market: str,
    start: str,
    end: str,
    points: str | None = None,
    x_trigger_secret: str = Header(default=""),
) -> dict[str, object]:
    """Load history for one market over a date range, in the background.

    Guarded like /trigger: a backfill spends far more ERCOT rate-limit budget
    than a scheduled run, and an unguarded one could starve live ingest.
    """
    secret = config.trigger_secret()
    if not secret or x_trigger_secret != secret:
        raise HTTPException(status_code=401, detail="invalid trigger secret")
    try:
        lo = date.fromisoformat(start)
        hi = date.fromisoformat(end)
        return backfill_mod.start(market, backfill_mod.resolve_points(points), lo, hi)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
