#!/usr/bin/env python3
"""Freeze a sheet into sheet_snapshots — the pre-registration step.

    python scripts/freeze_sheet.py NOV2026Monthly --auction 2026-11
    python scripts/freeze_sheet.py NOV2026Monthly-faded --auction 2026-11 \\
        --from-json ~/ercotcron-archive/ref/market_scan_faded_202611.json

Replicates the ticket's own derivation (app/bids/page.tsx; first written as
SQL in migration 20260906210000 for OCT): margin limit = ceiling / 1.5,
lottery cap under 50c clears, red when the limit does not beat the usual
clear, Market rows never green, sizing by ~$250 outlay and half the largest
award. The TOU hours used for sizing are the TARGET auction's real counts
(lib/auction.ts), not October's.

Default source is the live path_valuations (books Market + Discovery) — what
the /bids page is showing at freeze time. --from-json freezes a scan side
file instead (e.g. the rows the fade detector removed), as a shadow sheet.

Refuses to run twice for one sheet: the register never re-cuts.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg

# Computed by ercot/calendar.py over each delivery month (mirrors lib/auction.ts).
HOURS = {
    "2026-10": {"PeakWD": 352, "PeakWE": 144, "Off-peak": 248},
    "2026-11": {"PeakWD": 320, "PeakWE": 160, "Off-peak": 240},
}

DERIVE = """
insert into sheet_snapshots
  (sheet, source, sink, time_of_use, hedge_type, book, tier,
   ref_limit, suggested_mw, typical, worth, cleared_basis)
select %(sheet)s, v.source, v.sink, v.time_of_use, v.hedge_type, v.book,
       case
         when v.value_mean is null or v.ceiling is null then 'red'
         when d.ref < 0.1 then 'red'
         when v.cleared_price is not null and v.cleared_price > 0
              and d.ref / v.cleared_price <= 1.0 then 'red'
         when v.book = 'Market' then 'amber'
         when v.cleared_price is not null and v.warnings is null
              and v.cleared_price > 0 and d.ref / v.cleared_price > 1.05
              and (coalesce(v.cleared_price, d.ref) < 0.75
                   or (coalesce(v.cleared_price, d.ref) <= 5
                       and d.ref / v.cleared_price >= 2.0)) then 'green'
         else 'amber'
       end,
       d.ref,
       case
         when v.value_mean is null or v.ceiling is null or d.ref < 0.1
              or (v.cleared_price is not null and v.cleared_price > 0
                  and d.ref / v.cleared_price <= 1.0) then 0
         else greatest(1, least(
                floor(250.0 / greatest(
                  (case v.time_of_use when 'PeakWD' then %(wd)s
                                      when 'PeakWE' then %(we)s else %(op)s end)
                  * coalesce(nullif(v.cleared_price, 0), d.ref, 0.1), 1)),
                greatest(floor(coalesce(v.mw, 10) / 2), 1), 200))
       end,
       v.value_typical, v.value_mean, v.cleared_price
  from ({source}) v
  cross join lateral (
    select case when v.cleared_price is not null and v.cleared_price < 0.5
                then least(v.ceiling / 1.5, greatest(3 * v.cleared_price, 0.1))
                else v.ceiling / 1.5 end as ref
  ) d
"""

LIVE = """select book, source, sink, time_of_use, hedge_type, value_mean, value_typical,
                 ceiling, cleared_price, mw, warnings
            from path_valuations where book in ('Market', 'Discovery')"""

FROM_JSON = """select x.* from jsonb_to_recordset(%(rows)s::jsonb) as x(
                 book text, source text, sink text, time_of_use text, hedge_type text,
                 value_mean numeric, value_typical numeric, ceiling numeric,
                 cleared_price numeric, mw numeric, warnings text)"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--auction", required=True, choices=sorted(HOURS), help="delivery month YYYY-MM")
    ap.add_argument("--from-json", help="scan side file to freeze instead of path_valuations")
    ap.add_argument("--book", default="Market", help="book label for --from-json rows")
    args = ap.parse_args()
    h = HOURS[args.auction]
    params = {"sheet": args.sheet, "wd": h["PeakWD"], "we": h["PeakWE"], "op": h["Off-peak"]}

    if args.from_json:
        raw = json.loads(pathlib.Path(args.from_json).expanduser().read_text())
        params["rows"] = json.dumps([{
            "book": args.book, "source": r["source"], "sink": r["sink"],
            "time_of_use": r["tou"], "hedge_type": r["hedge"],
            "value_mean": r["worth"], "value_typical": r["typical_month"],
            "ceiling": r["ceiling"], "cleared_price": r["cleared"],
            "mw": r["mw_max_auction"], "warnings": r.get("fade") or r.get("warnings"),
        } for r in raw])
        sql = DERIVE.format(source=FROM_JSON)
    else:
        sql = DERIVE.format(source=LIVE)

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        n = cur.execute("select count(*) from sheet_snapshots where sheet = %s",
                        (args.sheet,)).fetchone()[0]
        if n:
            print(f"{args.sheet} already frozen ({n} rows) — the register does not re-cut")
            return 1
        cur.execute(sql, params)
        c.commit()
        cur.execute("""select tier, count(*), sum(suggested_mw) from sheet_snapshots
                        where sheet = %s group by 1 order by 1""", (args.sheet,))
        for tier, k, mw in cur.fetchall():
            print(f"  {tier:<6}{k:>5} rows  {mw or 0:>7} MW suggested")
    print(f"froze {args.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
