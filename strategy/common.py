"""Shared plumbing for the research CLIs — the end of laptop-only paths.

Every strategy script used to hard-code ~/ercotcron-archive, ~/Downloads and,
in one case, today's date. Now:

  ERCOTCRON_ARCHIVE   root of the local archive (default ~/ercotcron-archive)
  ERCOTCRON_REF       ref-file directory (default <archive>/ref)
  SCAN_TODAY          override "today" (YYYY-MM-DD) for reproducing a past run

and load_ref() falls back to the artifacts table (name 'ref/<stem>') when the
file is missing, so any machine with DATABASE_URL can run the pipeline —
the ref files are conveniences, the database is the source of record.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

ARCHIVE = pathlib.Path(os.environ.get("ERCOTCRON_ARCHIVE",
                                      str(pathlib.Path.home() / "ercotcron-archive")))
REF = pathlib.Path(os.environ.get("ERCOTCRON_REF", str(ARCHIVE / "ref")))
CACHE = ARCHIVE / "cache"
CACHES = [CACHE, pathlib.Path("/tmp")]
OUT = pathlib.Path(os.environ.get("ERCOTCRON_OUT", str(ARCHIVE / "out")))


def scan_today() -> dt.date:
    """Today, or SCAN_TODAY=YYYY-MM-DD to reproduce a historical run."""
    v = os.environ.get("SCAN_TODAY")
    return dt.date.fromisoformat(v) if v else dt.date.today()


def load_ref(name: str):
    """A ref JSON by filename ('constraint_exposure.json').

    File first (fast, offline); artifacts table 'ref/<stem>' second, writing
    the file back so the next run is offline again.
    """
    p = REF / name
    if p.exists():
        return json.loads(p.read_text())
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        cur.execute("select body from artifacts where name = %s",
                    (f"ref/{pathlib.Path(name).stem}",))
        row = cur.fetchone()
    if row is None:
        raise FileNotFoundError(f"{p} missing and no artifact ref/{pathlib.Path(name).stem}")
    try:
        REF.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(row[0]))
    except OSError:
        pass  # read-only host: serve from memory
    return row[0]


def dated_copy(path: pathlib.Path) -> pathlib.Path | None:
    """Snapshot an output file next to itself with today's date in the name.

    Lesson of the lost September vintage: a scan must snapshot BEFORE the next
    one overwrites. Returns the copy's path, or None if the source is missing.
    """
    if not path.exists():
        return None
    stamped = path.with_name(f"{path.stem}-{scan_today():%Y%m%d}{path.suffix}")
    stamped.write_bytes(path.read_bytes())
    return stamped
