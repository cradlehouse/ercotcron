"""Data access for the backtest harness.

Reads through Supabase's REST API with the anon key, which is enough because
the backtest only ever reads. Two things worth knowing before you trust a
number that comes out of here:

1. `price_from` and `ingested_at` on backfilled rows are the *backfill* time,
   not ERCOT's publication time. The `*_asof()` SQL functions are therefore
   vacuous for anything loaded before roughly 26 Jul 2026 — they return
   nothing for a historical as-of and everything for a current one. Only data
   collected live since then carries real bitemporal information.

2. So `spread()` builds the information set from delivery timestamps instead,
   which is exact for look-ahead on the primary series and blind to ERCOT's
   later revisions. That trade is stated, not hidden.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

_URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"].rstrip("/")
_KEY = os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
_H = {"apikey": _KEY, "Authorization": f"Bearer {_KEY}"}

PAGE = 1000  # PostgREST caps responses at 1000 rows regardless of `limit`.


def _page(path: str, order: str, cap: int = 2_000_000) -> list[dict]:
    out: list[dict] = []
    off = 0
    while off < cap:
        url = f"{_URL}/rest/v1/{path}&order={order}&limit={PAGE}&offset={off}"
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers=_H)
                with urllib.request.urlopen(req, timeout=180) as resp:
                    batch = json.loads(resp.read())
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))
        out.extend(batch)
        if len(batch) < PAGE:
            break
        off += PAGE
    return out


def tracked_points() -> list[str]:
    rows = _page("settlement_points?select=name,point_type&active=eq.true", "name.asc")
    return [r["name"] for r in rows if r["point_type"] in ("HU", "AH", "SH")]


def spread(points: list[str], start: str, end: str) -> list[dict]:
    """Hourly DA minus RT per point over [start, end).

    RT is averaged across the four 15-minute intervals in the hour. Hours where
    either side is missing are dropped rather than zero-filled — a missing RT
    price is not a zero spread.
    """
    # `+00:00` in an ISO timestamp decodes as a space inside a query string,
    # so every bound has to be percent-encoded or PostgREST returns 400.
    lo = urllib.parse.quote(start, safe="")
    hi = urllib.parse.quote(end, safe="")
    inlist = urllib.parse.quote("(" + ",".join(f'"{p}"' for p in points) + ")", safe="(),\"")
    dam = _page(
        f"dam_spp?settlement_point=in.{inlist}"
        f"&interval_start=gte.{lo}&interval_start=lt.{hi}"
        "&select=settlement_point,interval_start,price",
        "settlement_point.asc,interval_start.asc",
    )
    rt = _page(
        f"rt_spp?settlement_point=in.{inlist}"
        f"&interval_start=gte.{lo}&interval_start=lt.{hi}"
        "&select=settlement_point,interval_start,price",
        "settlement_point.asc,interval_start.asc",
    )
    buckets: dict[tuple[str, str], list[float]] = {}
    for r in rt:
        buckets.setdefault((r["settlement_point"], r["interval_start"][:13]), []).append(
            float(r["price"])
        )
    rows = []
    for d in dam:
        key = (d["settlement_point"], d["interval_start"][:13])
        vals = buckets.get(key)
        if not vals:
            continue
        rows.append({
            "settlement_point": d["settlement_point"],
            "interval_start": d["interval_start"],
            "da": float(d["price"]),
            "rt": sum(vals) / len(vals),
            "spread": float(d["price"]) - sum(vals) / len(vals),
        })
    rows.sort(key=lambda r: (r["settlement_point"], r["interval_start"]))
    return rows
