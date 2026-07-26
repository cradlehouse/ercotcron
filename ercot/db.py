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


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.database_url(),
            min_size=1,
            max_size=4,
            kwargs={"application_name": "ercotcron"},
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

    changed = sql.SQL(" or ").join(
        sql.SQL("{t}.{c} is distinct from excluded.{c}").format(t=ident(table), c=ident(c))
        for c in update
    )
    assignments = sql.SQL(", ").join(
        sql.SQL("{c} = excluded.{c}").format(c=ident(c)) for c in update
    )

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
                "insert into {tbl} ({cols}) select {cols} from {tmp} "
                "on conflict ({conflict}) do update set {assignments} "
                "where {changed} "
                "returning (xmax = 0) as inserted"
            ).format(
                tbl=ident(table),
                cols=cols,
                tmp=ident(temp),
                conflict=sql.SQL(", ").join(ident(c) for c in conflict),
                assignments=assignments,
                changed=changed,
            )
        )
        results = cur.fetchall()
        conn.commit()

    inserted = sum(1 for r in results if r[0])
    return inserted, len(results) - inserted


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


def ping() -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select 1")
        return cur.fetchone()[0] == 1
