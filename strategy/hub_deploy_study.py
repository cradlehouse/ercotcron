#!/usr/bin/env python3
"""Hub-leg deployment book — the scale experiment, pre-registered.

The capacity map (Sep 2026) showed ~$30M/month of real buy-side flow on
~2,600 hub/zone-leg paths, where a five-figure book moves no prices. This
study values that universe with the house machinery and freezes a shadow
sheet for NOVEMBER weeks before its auction, so it is graded — fills, then
settlement — exactly like the published sheet, before a dollar of advice
rides on it.

Scope (v1, stated up front): OBL, PeakWD + PeakWE only. Payouts come from
node_day_spread (peak-hours daily node-vs-hub spreads), so off-peak and OPT
optionality are out of scope until the daily table grows an off-peak twin.

Rules, incorporating the September lessons:
  value      = MEDIAN month payout (HKSN lesson: means chase spikes)
  fit window = Sep 2025 .. Jul 2026; Aug 2026 is HELD OUT (house holdout
               rule) and reported, never fitted on
  keep if    months-positive >= 7/11, median >= 2x clearing basis,
             basis >= $0.02, no fade (Jul-26 >= 0.25 x median)
  limit      = median / 1.5
  size       = the market's own average bought MW on the path (capped 25)
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import statistics
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg
from dotenv import load_dotenv

from ercot.calendar import tou_of

load_dotenv(ROOT / ".env")

SHEET = "NOV2026Monthly-hubshadow"
FIT_START, FIT_END = dt.date(2025, 9, 1), dt.date(2026, 8, 1)   # Aug26 held out
HOLDOUT = dt.date(2026, 8, 1)


def main() -> int:
    c = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40)
    c.execute("set statement_timeout = '10min'")
    cur = c.cursor()

    n = cur.execute("select count(*) from sheet_snapshots where sheet=%s", (SHEET,)).fetchone()[0]
    if n:
        print(f"{SHEET} already frozen ({n} rows) — the register does not re-cut")
        return 0

    # Universe: hub/zone-leg OBL paths with real recent buy volume
    cur.execute("""
      select source, sink, time_of_use,
             avg(mwsum) as avg_mw,
             coalesce(avg(cp) filter (where cp is not null), 0) as basis
      from (
        select auction_name, source, sink, time_of_use,
               sum(mw) filter (where bid_type='BUY') as mwsum,
               coalesce(avg(clearing_price) filter (where not bid24hour),
                        avg(clearing_price)) as cp
        from crr_awards
        where auction_name in ('AUG2026Monthly','SEP2026Monthly','OCT2026Monthly')
          and hedge_type = 'OBL' and time_of_use in ('PeakWD','PeakWE')
          and (source like 'HB\\_%' or source like 'LZ\\_%'
               or sink like 'HB\\_%' or sink like 'LZ\\_%')
        group by 1,2,3,4) t
      where mwsum > 0
      group by 1,2,3
      having count(*) >= 2 and avg(mwsum) >= 2""")
    universe = cur.fetchall()
    print(f"universe: {len(universe)} hub-leg OBL path-blocks with recurring buy volume")

    # Daily spreads for every node in the universe, one pull
    nodes = sorted({r[0] for r in universe} | {r[1] for r in universe})
    cur.execute("""
      select settlement_point, delivery_date, spread from node_day_spread
      where settlement_point = any(%s) and delivery_date >= %s""",
                (nodes, FIT_START))
    sp: dict = defaultdict(dict)
    for node, d, s in cur.fetchall():
        sp[node][d] = float(s)

    kept, rows = 0, []
    holdout_kept, holdout_all = [], []
    for src, snk, tou, avg_mw, basis in universe:
        basis = float(basis)
        months: dict = defaultdict(list)
        hold: list = []
        for d, s_src in sp.get(src, {}).items():
            s_snk = sp.get(snk, {}).get(d)
            if s_snk is None:
                continue
            if tou_of(d, 12) != tou:      # day-level block classification
                continue
            spread = s_snk - s_src
            if FIT_START <= d < FIT_END:
                months[(d.year, d.month)].append(spread)
            elif HOLDOUT <= d < HOLDOUT + dt.timedelta(days=31):
                hold.append(spread)
        mm = {k: statistics.mean(v) for k, v in months.items() if len(v) >= 3}
        if len(mm) < 9:
            continue
        med = statistics.median(mm.values())
        pos = sum(1 for v in mm.values() if v > 0)
        jul = mm.get((2026, 7))
        hold_avg = statistics.mean(hold) if hold else None
        if hold_avg is not None:
            holdout_all.append(hold_avg - basis)
        if not (med >= 2 * basis and basis >= 0.02 and pos >= 7
                and jul is not None and jul >= 0.25 * med):
            continue
        kept += 1
        if hold_avg is not None:
            holdout_kept.append(hold_avg - basis)
        rows.append((SHEET, src, snk, tou, 'OBL', 'HubDeploy', 'amber',
                     round(med / 1.5, 4), min(round(float(avg_mw)), 25),
                     round(med, 4), round(med, 4), round(basis, 4)))

    cur.executemany("""
      insert into sheet_snapshots
        (sheet, source, sink, time_of_use, hedge_type, book, tier,
         ref_limit, suggested_mw, typical, worth, cleared_basis)
      values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
    c.commit()

    dollars = sum(r[8] * r[11] * (352 if r[3] == 'PeakWD' else 144) for r in rows)
    print(f"kept {kept} of {len(universe)} — frozen as {SHEET}")
    print(f"deployable at basis clears, market-sized: ${dollars:,.0f} for November")
    if holdout_kept and holdout_all:
        print("HOLDOUT (Aug-26, never fitted): picks avg spread-minus-basis "
              f"${statistics.mean(holdout_kept):+.2f}/MWh vs universe ${statistics.mean(holdout_all):+.2f}/MWh")
    for r in sorted(rows, key=lambda r: -r[8] * r[11])[:8]:
        print(f"  {r[1]}→{r[2]} {r[3]}: median ${r[9]}/MWh vs clears ${r[11]} | "
              f"limit ${r[7]} | {r[8]} MW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
