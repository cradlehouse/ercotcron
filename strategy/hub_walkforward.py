#!/usr/bin/env python3
"""Ten-month walk-forward of the hub-leg deployment screen.

For each test month DEC2025..SEP2026: universe and clearing basis from the
three prior monthly auctions only; value = median of the 11 fit months
ending two months before the test month (house holdout); fade gate on the
last fit month; fills graded at the test month's real clears (buy volume
required); settlement paid from node_day_spread over the test month's own
days. Nothing in any month's decision uses information from after its
auction closed.

Scope matches strategy/hub_deploy_study.py: hub/zone-leg, OBL, peak blocks.
"""
from __future__ import annotations

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

MONTHS = ['SEP2025', 'OCT2025', 'NOV2025', 'DEC2025', 'JAN2026', 'FEB2026',
          'MAR2026', 'APR2026', 'MAY2026', 'JUN2026', 'JUL2026', 'AUG2026', 'SEP2026']
IDX = {m: i + 1 for i, m in enumerate(
    ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}


def ym(tag: str) -> tuple[int, int]:
    return int(tag[3:]), IDX[tag[:3]]


def main() -> int:
    c = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40)
    c.execute("set statement_timeout = '10min'")
    cur = c.cursor()
    cur.execute("""
      select auction_name, source, sink, time_of_use,
             sum(mw) filter (where bid_type='BUY'),
             coalesce(avg(clearing_price) filter (where not bid24hour), avg(clearing_price))
      from crr_awards
      where auction_name like '%Monthly' and hedge_type='OBL'
        and time_of_use in ('PeakWD','PeakWE')
        and (source like 'HB\\_%' or source like 'LZ\\_%'
             or sink like 'HB\\_%' or sink like 'LZ\\_%')
      group by 1,2,3,4""")
    A: dict = defaultdict(dict)
    for an, src, snk, tou, mw, cp in cur.fetchall():
        A[(src, snk, tou)][an.replace('Monthly', '')] = (
            float(mw or 0), float(cp) if cp is not None else None)
    nodes = sorted({k[0] for k in A} | {k[1] for k in A})
    cur.execute("select settlement_point, delivery_date, spread from node_day_spread "
                "where settlement_point = any(%s)", (nodes,))
    sp: dict = defaultdict(dict)
    for n, d, s in cur.fetchall():
        sp[n][d] = float(s)
    print(f"{len(A)} path-blocks, {len(nodes)} nodes", flush=True)

    def month_avg(src, snk, tou, yy, mm):
        v = [sp[snk][d] - sp[src][d] for d in sp.get(src, {})
             if d.year == yy and d.month == mm and tou_of(d, 12) == tou
             and d in sp.get(snk, {})]
        return statistics.mean(v) if len(v) >= 3 else None

    print(f"{'month':<9}{'picks':>6}{'fills':>6}{'$in':>10}{'$out':>10}{'ret':>6}")
    tot_in = tot_out = 0.0
    for ti in range(3, len(MONTHS)):
        test = MONTHS[ti]
        ty, tm = ym(test)
        basis_names = [MONTHS[ti - 1], MONTHS[ti - 2], MONTHS[ti - 3]]
        fit_months = []
        for k in range(2, 13):
            mm, yy = tm - k, ty
            while mm <= 0:
                mm += 12
                yy -= 1
            fit_months.append((yy, mm))
        picks = fills = 0
        mi = mo = 0.0
        for (src, snk, tou), aucs in A.items():
            hist = [aucs[b] for b in basis_names if b in aucs and aucs[b][0] > 0]
            if len(hist) < 2:
                continue
            avg_mw = statistics.mean(h[0] for h in hist)
            bs = [h[1] for h in hist if h[1] is not None]
            if avg_mw < 2 or not bs:
                continue
            basis = statistics.mean(bs)
            vals = {}
            for (yy, mm) in fit_months:
                v = month_avg(src, snk, tou, yy, mm)
                if v is not None:
                    vals[(yy, mm)] = v
            if len(vals) < 8:
                continue
            med = statistics.median(vals.values())
            pos = sum(1 for v in vals.values() if v > 0)
            fade = vals.get(fit_months[0])
            if not (med >= 2 * basis and basis >= 0.02 and pos >= 7
                    and fade is not None and fade >= 0.25 * med):
                continue
            picks += 1
            t = aucs.get(test)
            if t is None or t[1] is None or med / 1.5 < t[1] or t[0] <= 0:
                continue
            fills += 1
            mw = min(round(avg_mw), 25)
            days = [d for d in sp.get(src, {}) if d.year == ty and d.month == tm
                    and tou_of(d, 12) == tou and d in sp.get(snk, {})]
            mi += t[1] * 16 * len(days) * mw
            mo += sum(sp[snk][d] - sp[src][d] for d in days) * 16 * mw
        tot_in += mi
        tot_out += mo
        print(f"{test:<9}{picks:>6}{fills:>6}{mi:>10,.0f}{mo:>10,.0f}"
              f"{(100 * mo / mi if mi else 0):>5.0f}%", flush=True)
    if tot_in:
        print(f"{'TOTAL':<9}{'':>6}{'':>6}{tot_in:>10,.0f}{tot_out:>10,.0f}"
              f"{100 * tot_out / tot_in:>5.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
