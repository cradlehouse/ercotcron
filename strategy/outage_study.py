#!/usr/bin/env python3
"""Outage-sensitivity study, run as a PREDICTION and graded on a held-out
episode — instance-friendly edition.

Phase 1 precomputes node_day_spread once (per node per day: peak-hours DAM
price minus HB_HUBAVG), month by month with pauses, so the heavy table is
touched gently and exactly once. All-node DAM coverage begins Sep 2024, so
the study window is 2024-09-15 onward (~1,000 settlement points).

Phase 2, per large unit: episodes from resource_outages; TRAIN node deltas
(down vs matched control days) on all episodes except the most recent; TEST
on the held-out final episode; grade sign agreement of the top movers. The
return leg (first 14 days back) is measured too. Results in
outage_node_deltas.

IN-SAMPLE + one held-out episode per unit — still short of full walk-forward
(negative_knowledge #16); nothing prices a sheet from here yet.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import time
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psycopg
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

WINDOW_START = dt.date(2024, 9, 15)
UNITS = [
    "STP_STP_G1", "STP_STP_G2", "CPSES_UNIT1", "CPSES_UNIT2",
    "MLSES_UNIT1", "MLSES_UNIT2", "MLSES_UNIT3",
    "LEG_LEG_G1", "LEG_LEG_G2", "OGSES_UNIT1A", "OGSES_UNIT2", "SCES_UNIT1",
]

EPISODES_Q = """
select min(outage_start::date) s, max(coalesce(planned_end::date, outage_start::date)) e
from (select *, sum(brk) over (order by outage_start) grp
      from (select outage_start, planned_end,
                   case when outage_start::date - lag(coalesce(planned_end::date, outage_start::date))
                        over (order by outage_start) > 14 then 1 else 0 end brk
            from resource_outages
            where unit_code = %(unit)s and reduction_mw >= 400) x) y
group by grp
having max(coalesce(planned_end::date, outage_start::date)) - min(outage_start::date) >= 7
   and min(outage_start::date) >= %(win)s
order by 1
"""


def precompute(c) -> None:
    c.execute("""
      create table if not exists node_day_spread (
        delivery_date date not null,
        settlement_point text not null,
        spread numeric not null,
        primary key (delivery_date, settlement_point))""")
    c.execute("alter table node_day_spread enable row level security")
    c.execute("revoke all on node_day_spread from anon, authenticated")
    c.commit()
    mo = dt.date(WINDOW_START.year, WINDOW_START.month, 1)
    today = dt.date.today()
    while mo <= today:
        nxt = (mo.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        n = c.execute("select count(*) from node_day_spread where delivery_date >= %s and delivery_date < %s",
                      (mo, nxt)).fetchone()[0]
        if n == 0:
            t0 = time.time()
            c.execute("""
              insert into node_day_spread
              with hub as (
                select delivery_date, avg(price) hp from dam_spp
                where settlement_point = 'HB_HUBAVG' and hour_ending between 7 and 22
                  and delivery_date >= %s and delivery_date < %s
                group by 1)
              select s.delivery_date, s.settlement_point,
                     round((avg(s.price) - h.hp)::numeric, 3)
              from dam_spp s join hub h on h.delivery_date = s.delivery_date
              where s.hour_ending between 7 and 22
                and s.delivery_date >= %s and s.delivery_date < %s
              group by s.delivery_date, s.settlement_point, h.hp
              on conflict do nothing""", (mo, nxt, mo, nxt))
            c.commit()
            print(f"precompute {mo:%Y-%m}: {time.time()-t0:.0f}s", flush=True)
            time.sleep(3)  # let the instance breathe
        mo = nxt


def day_sets(eps: list, i: int):
    s, e = eps[i]
    e_cap = min(e, s + dt.timedelta(days=90))
    down = {s + dt.timedelta(days=d) for d in range((e_cap - s).days + 1)}
    ret = {e + dt.timedelta(days=d) for d in range(1, 15)} - down
    ctrl = {s + dt.timedelta(days=d)
            for d in range(-45, (e_cap - s).days + 46)} - down - ret
    return down, ret, ctrl


def main() -> int:
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        c.execute("set statement_timeout = '10min'")
        precompute(c)
        c.execute("""
          create table if not exists outage_node_deltas (
            unit_code text not null,
            settlement_point text not null,
            train_episodes int, train_down_days int, train_ctrl_days int,
            train_delta numeric, return_delta numeric,
            test_down_days int, test_delta numeric, sign_match boolean,
            computed_at timestamptz not null default now(),
            primary key (unit_code, settlement_point))""")
        c.execute("alter table outage_node_deltas enable row level security")
        c.execute("revoke all on outage_node_deltas from anon, authenticated")
        c.commit()

        for u in UNITS:
            eps = c.execute(EPISODES_Q, {"unit": u, "win": WINDOW_START}).fetchall()
            if len(eps) < 2:
                print(f"{u}: {len(eps)} in-window episode(s) — need 2+, skipped", flush=True)
                continue
            t0 = time.time()

            def pull(days):
                if not days:
                    return {}
                rows = c.execute(
                    "select settlement_point, count(*), avg(spread) from node_day_spread "
                    "where delivery_date = any(%s) group by 1", (sorted(days),)).fetchall()
                return {sp: (n, float(m)) for sp, n, m in rows}

            acc = defaultdict(lambda: [0, 0.0, 0, 0.0, 0, 0.0, 0])  # dn n/sum, ct n/sum, rt n/sum, eps
            for i in range(len(eps) - 1):
                down, ret, ctrl = day_sets(eps, i)
                pd, pr, pc = pull(down), pull(ret), pull(ctrl)
                for sp in pc:
                    a = acc[sp]
                    if sp in pd:
                        a[0] += pd[sp][0]; a[1] += pd[sp][1] * pd[sp][0]
                    a[2] += pc[sp][0]; a[3] += pc[sp][1] * pc[sp][0]
                    if sp in pr:
                        a[4] += pr[sp][0]; a[5] += pr[sp][1] * pr[sp][0]
                    a[6] += 1
            down, ret, ctrl = day_sets(eps, len(eps) - 1)
            td, tc = pull(down), pull(ctrl)
            test = {sp: (td[sp][0], td[sp][1] - tc[sp][1]) for sp in td if sp in tc}

            rows = []
            for sp, a in acc.items():
                if a[0] < 10 or a[2] < 20:
                    continue
                train_delta = a[1] / a[0] - a[3] / a[2]
                ret_delta = (a[5] / a[4] - a[3] / a[2]) if a[4] >= 5 else None
                t = test.get(sp)
                rows.append((u, sp, a[6], a[0], a[2],
                             round(train_delta, 3),
                             round(ret_delta, 3) if ret_delta is not None else None,
                             t[0] if t else None,
                             round(t[1], 3) if t else None,
                             (train_delta > 0) == (t[1] > 0) if t else None))
            rows.sort(key=lambda r: -abs(r[5]))
            n_top = sum(1 for r in rows[:25] if r[9] is not None)
            n_match = sum(1 for r in rows[:25] if r[9])
            c.cursor().executemany(
                """insert into outage_node_deltas
                     (unit_code, settlement_point, train_episodes, train_down_days,
                      train_ctrl_days, train_delta, return_delta,
                      test_down_days, test_delta, sign_match)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (unit_code, settlement_point) do update set
                     train_episodes=excluded.train_episodes,
                     train_down_days=excluded.train_down_days,
                     train_ctrl_days=excluded.train_ctrl_days,
                     train_delta=excluded.train_delta,
                     return_delta=excluded.return_delta,
                     test_down_days=excluded.test_down_days,
                     test_delta=excluded.test_delta,
                     sign_match=excluded.sign_match,
                     computed_at=now()""", rows)
            c.commit()
            print(f"{u}: {len(eps)-1} train eps, test {eps[-1][0]}..{eps[-1][1]}, "
                  f"{len(rows)} nodes, top-25 sign agreement {n_match}/{n_top} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
