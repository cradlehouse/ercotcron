"""Database access: pooled Postgres connection, bulk upserts, run bookkeeping.

Ingest writes over a direct Postgres connection rather than PostgREST. A
five-minute tick can carry thousands of rows; COPY into an unlogged temp table
followed by a single INSERT ... ON CONFLICT is one round trip instead of
thousands, and it keeps the revision triggers in charge of history.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _through_transaction_pooler(url: str) -> bool:
    """Whether the connection lands on a transaction-mode pooler.

    Supabase's shared pooler (Supavisor) runs transaction mode on 6543 and
    session mode on 5432; the dedicated pooler also uses 6543.
    """
    return ":6543" in url or "pooler.supabase.com" in url


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = config.database_url()
        kwargs: dict[str, object] = {"application_name": "ercotcron"}
        if _through_transaction_pooler(url):
            # Transaction mode hands out a different backend per statement, so a
            # prepared statement is never found where it was created. psycopg
            # prepares automatically after five executions, which makes this
            # fail only once a job has been running a while — long after the
            # deploy that introduced it looked successful.
            kwargs["prepare_threshold"] = None
        _pool = ConnectionPool(
            url,
            min_size=1,
            max_size=4,
            kwargs=kwargs,
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# --------------------------------------------------------------- upserts --


def upsert_rows(
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    conflict: Sequence[str],
    update: Sequence[str],
) -> tuple[int, int]:
    """Bulk upsert. Returns (inserted, updated).

    Rows whose values are unchanged are skipped in the WHERE clause, so an
    unchanged re-pull produces no writes and no spurious revision history.
    """
    rows = list(rows)
    if not rows:
        return (0, 0)

    ident = sql.Identifier
    cols = sql.SQL(", ").join(ident(c) for c in columns)
    temp = f"tmp_{table}"

    key_match = sql.SQL(" and ").join(
        sql.SQL("{t}.{c} = {tmp}.{c}").format(t=ident(table), tmp=ident(temp), c=ident(c))
        for c in conflict
    )
    changed = sql.SQL(" or ").join(
        sql.SQL("{t}.{c} is distinct from {tmp}.{c}").format(
            t=ident(table), tmp=ident(temp), c=ident(c)
        )
        for c in update
    )
    assignments = sql.SQL(", ").join(
        sql.SQL("{c} = {tmp}.{c}").format(c=ident(c), tmp=ident(temp)) for c in update
    )

    # Update-then-insert rather than ON CONFLICT with `returning xmax = 0`:
    # Postgres refuses system columns on partitioned tables ("cannot retrieve a
    # system column in this context"), and the 5-minute tables are partitioned
    # by month. Two statements in one transaction give the same counts without
    # touching a system column. Safe against concurrent writers only because
    # there are none: APScheduler runs each job with max_instances=1, and each
    # table has exactly one writing job.
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "create temp table {tmp} (like {tbl} including defaults) "
                "on commit drop"
            ).format(tmp=ident(temp), tbl=ident(table))
        )

        copy_stmt = sql.SQL("copy {tmp} ({cols}) from stdin").format(
            tmp=ident(temp), cols=cols
        )
        with cur.copy(copy_stmt) as copy:
            for row in rows:
                copy.write_row(row)

        cur.execute(
            sql.SQL(
                "update {tbl} set {assignments} from {tmp} "
                "where {key_match} and ({changed})"
            ).format(
                tbl=ident(table),
                assignments=assignments,
                tmp=ident(temp),
                key_match=key_match,
                changed=changed,
            )
        )
        updated = cur.rowcount

        cur.execute(
            sql.SQL(
                "insert into {tbl} ({cols}) select {cols} from {tmp} "
                "on conflict ({conflict}) do nothing"
            ).format(
                tbl=ident(table),
                cols=cols,
                tmp=ident(temp),
                conflict=sql.SQL(", ").join(ident(c) for c in conflict),
            )
        )
        inserted = cur.rowcount
        conn.commit()

    return inserted, updated


def insert_rows_ignore_dupes(
    table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]], *, conflict: Sequence[str]
) -> int:
    """Insert-only load for append-only tables (RTD forecast vintages)."""
    rows = list(rows)
    if not rows:
        return 0

    ident = sql.Identifier
    cols = sql.SQL(", ").join(ident(c) for c in columns)
    temp = f"tmp_{table}"

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "create temp table {tmp} (like {tbl} including defaults) on commit drop"
            ).format(tmp=ident(temp), tbl=ident(table))
        )
        with cur.copy(
            sql.SQL("copy {tmp} ({cols}) from stdin").format(tmp=ident(temp), cols=cols)
        ) as copy:
            for row in rows:
                copy.write_row(row)

        cur.execute(
            sql.SQL(
                "insert into {tbl} ({cols}) select {cols} from {tmp} "
                "on conflict ({conflict}) do nothing returning 1"
            ).format(
                tbl=ident(table),
                cols=cols,
                tmp=ident(temp),
                conflict=sql.SQL(", ").join(ident(c) for c in conflict),
            )
        )
        count = len(cur.fetchall())
        conn.commit()
    return count


def upsert_settlement_points(points: Iterable[tuple[str, str | None, str | None]]) -> int:
    rows = [(name, ptype, zone) for name, ptype, zone in points if name]
    if not rows:
        return 0
    inserted, updated = upsert_rows(
        "settlement_points",
        ["name", "point_type", "zone"],
        rows,
        conflict=["name"],
        update=["point_type", "zone"],
    )
    with connection() as conn, conn.cursor() as cur:
        cur.execute("update settlement_points set updated_at = now() where name = any(%s)",
                    ([r[0] for r in rows],))
        conn.commit()
    return inserted + updated


# ---------------------------------------------------------- run tracking --


def start_run(job: str, window_start: datetime | None, window_end: datetime | None) -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "insert into ingest_runs (job, window_start, window_end) values (%s, %s, %s) "
            "returning id",
            (job, window_start, window_end),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    return run_id


def finish_run(
    run_id: int,
    *,
    status: str,
    requests: int = 0,
    rows_seen: int = 0,
    rows_inserted: int = 0,
    rows_revised: int = 0,
    error: str | None = None,
) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "update ingest_runs set finished_at = now(), status = %s, requests = %s, "
            "rows_seen = %s, rows_inserted = %s, rows_revised = %s, error = %s "
            "where id = %s",
            (status, requests, rows_seen, rows_inserted, rows_revised,
             (error or None) and error[:4000], run_id),
        )
        conn.commit()


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select id, job, started_at, finished_at, status, rows_seen, rows_inserted, "
            "rows_revised, error from ingest_runs order by started_at desc limit %s",
            (limit,),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ------------------------------------------------- partition maintenance --


def ensure_partitions(months_ahead: int = 3) -> list[str]:
    """Create monthly partitions for the current month and the next N."""
    created: list[str] = []
    with connection() as conn, conn.cursor() as cur:
        for table in ("rt_lmp_5min", "rtd_lmp"):
            for offset in range(months_ahead + 1):
                cur.execute(
                    "select ensure_month_partition(%s, (date_trunc('month', now()) "
                    "+ make_interval(months => %s))::date)",
                    (table, offset),
                )
                created.append(cur.fetchone()[0])
        conn.commit()
    return created


def default_partition_rows() -> dict[str, int]:
    """Rows that landed in a default partition — the sign partitioning stalled."""
    counts: dict[str, int] = {}
    with connection() as conn, conn.cursor() as cur:
        for table in ("rt_lmp_5min_default", "rtd_lmp_default"):
            cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table)))
            counts[table] = cur.fetchone()[0]
    return counts


def ping(timeout: float = 2.0) -> bool:
    """Cheap liveness probe with a hard deadline.

    The deadline is the point. Render restarts a container whose health check
    times out, so a ping that waits the pool's default 30s while a heavy job
    holds the connections will fail the health check and kill the process —
    taking any running backfill with it. Better to report the database as
    briefly unavailable than to be restarted for saying nothing.
    """
    with pool().connection(timeout=timeout) as conn, conn.cursor() as cur:
        cur.execute("select 1")
        return cur.fetchone()[0] == 1


def table_stats() -> dict[str, object]:
    """Row counts and on-disk size per price table, plus the database total.

    Supabase's free tier caps the database at 500MB, and a backfill is the one
    operation that can approach it. Knowing the size before loading more is the
    difference between stopping deliberately and having live ingest start
    failing on a full disk.
    """
    tables = ("dam_spp", "rt_spp", "rt_lmp_5min", "rtd_lmp",
              "dam_spp_history", "rt_spp_history", "ingest_runs",
              "wind_power", "solar_power", "load_forecast", "binding_constraints",
              "crr_awards", "crr_auctions", "crr_point_prices")
    out: dict[str, object] = {}
    with connection() as conn, conn.cursor() as cur:
        for table in tables:
            if cur.execute(
                "select to_regclass(%s) is not null", (table,)
            ).fetchone()[0] is not True:
                continue
            cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table)))
            rows = cur.fetchone()[0]
            cur.execute("select pg_total_relation_size(%s)", (table,))
            out[table] = {"rows": rows, "bytes": cur.fetchone()[0]}
        cur.execute("select pg_database_size(current_database())")
        total = cur.fetchone()[0]
    out["database_bytes"] = total
    out["database_mb"] = round(total / 1_048_576, 1)
    return out


def close_interrupted_runs(older_than_minutes: int = 5) -> int:
    """Mark runs still 'running' from a previous process as interrupted.

    A deploy replaces the container mid-run, so any in-flight job dies without
    reaching finish_run and its row stays 'running' forever. Left alone those
    rows accumulate and make the health page unreadable — and worse, they look
    like a job that hung rather than one that was replaced.

    The age guard matters: a job legitimately running in *this* process at
    startup must not be clobbered, and 5 minutes is longer than any scheduled
    job takes.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "update ingest_runs set status = 'error', finished_at = now(), "
            "error = 'interrupted by a restart or deploy' "
            "where status = 'running' "
            "and started_at < now() - make_interval(mins => %s)",
            (older_than_minutes,),
        )
        count = cur.rowcount
        conn.commit()
    return count
