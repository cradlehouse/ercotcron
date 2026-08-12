#!/usr/bin/env python3
"""Products 1 + 2: marks on every live CRR book, and stale-position alerts.

MARK MODEL (v1, deliberately simple and documentable):
  a position's remaining delivery months are each valued at the mean payoff of
  that CALENDAR month across available years of day-ahead settlement (an
  August is priced off Augusts), falling back to the all-months median where a
  calendar month has no history. OPT pays max(0, sink-source); OBL the signed
  mean. Position mark = sum over remaining months of MW x TOU-hours x value.
  Hours use the weekend rule; NERC holidays are approximated as weekends —
  stated, not hidden (worth <1% on a monthly strip).

ALERTS: a position is stale-flagged when either endpoint carries material
  exposure (|beta| >= 0.02) to a constraint re-rated in the last 90 days or
  silent for 60+. The flag means the history behind the mark may describe a
  network that no longer exists — which is exactly what a counterparty who has
  noticed will price against you.
"""
import calendar, collections, datetime as dt, json, os, pathlib, sys
import numpy as np
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import psycopg

REF = pathlib.Path.home() / "ercotcron-archive" / "ref"
CACHE = pathlib.Path.home() / "ercotcron-archive" / "cache"
TAGS = ["sep24","nov24","dec24","jan25","feb25","aug25","sep25","oct25","nov25",
        "dec25","jan26","feb26","mar26","apr26","may26","jun26","jul26"]
MON = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

def tou_of(d, he):
    return "Off-peak" if not (7 <= he <= 22) else ("PeakWD" if d.weekday() < 5 else "PeakWE")

def hours_in(year, month, tou):
    n = calendar.monthrange(year, month)[1]
    wd = sum(1 for day in range(1, n + 1) if dt.date(year, month, day).weekday() < 5)
    return {"PeakWD": 16 * wd, "PeakWE": 16 * (n - wd), "Off-peak": 8 * n}[tou]

def load_month(tag):
    p = CACHE / f"dam_{tag}.json"
    if p.exists():
        return json.loads(p.read_text())
    mon = MON[tag[:3]]; yr = 2000 + int(tag[3:])
    lo = dt.date(yr, mon, 1)
    hi = dt.date(yr + (mon == 12), (mon % 12) + 1, 1)
    print(f"  pulling {tag} from dam_spp...", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        c.execute("set statement_timeout='10min'")
        cur = c.cursor()
        cur.execute("""select settlement_point, delivery_date::text, hour_ending, price
                         from dam_spp where delivery_date >= %s and delivery_date < %s""", (lo, hi))
        rows = [{"settlement_point": r[0], "delivery_date": r[1],
                 "hour_ending": r[2], "price": float(r[3])} for r in cur.fetchall()]
    if rows:
        p.write_text(json.dumps(rows))
    return rows

print("building price matrix...", flush=True)
point_idx, hour_keys, cols = {}, [], []
for tag in TAGS:
    rows = load_month(tag)
    by_hour = collections.defaultdict(dict)
    for r in rows:
        i = point_idx.setdefault(r["settlement_point"], len(point_idx))
        by_hour[(r["delivery_date"], r["hour_ending"])][i] = r["price"]
    for k, prices in by_hour.items():
        hour_keys.append(k); cols.append(prices)
M = np.full((len(hour_keys), len(point_idx)), np.nan, dtype=np.float32)
for ri, prices in enumerate(cols):
    for ci, v in prices.items():
        M[ri, ci] = v
dts = [dt.date.fromisoformat(d) for d, _ in hour_keys]
tou_arr = np.array([tou_of(d, he) for d, (_, he) in zip(dts, hour_keys)])
cal_arr = np.array([d.month for d in dts])
masks = {t: tou_arr == t for t in ("Off-peak", "PeakWD", "PeakWE")}
print(f"matrix {len(hour_keys):,} x {len(point_idx):,}", flush=True)

with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
    c.execute("set statement_timeout='10min'")
    cur = c.cursor()
    cur.execute("""select account_holder, source, sink, time_of_use, hedge_type,
                          start_date, end_date, sum(mw)
                     from crr_awards where end_date >= '2026-09-01'
                    group by 1,2,3,4,5,6,7""")
    live = cur.fetchall()
    exp = json.loads((REF / "constraint_exposure.json").read_text())
    cur.execute("select constraint_name, recent_rerate, possibly_retired from constraint_novelty")
    nov = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
stale_nodes = {}
for cname, entries in exp.items():
    rr, ret = nov.get(cname, (False, False))
    if rr or ret:
        for e in entries:
            if abs(e["beta"]) >= 0.02:
                stale_nodes.setdefault(e["node"], cname)
print(f"live position groups: {len(live):,}", flush=True)

val_cache = {}
def month_value(src, snk, tou, hedge, cal_month):
    key = (src, snk, tou, hedge)
    if key not in val_cache:
        si, ki = point_idx.get(src), point_idx.get(snk)
        if si is None or ki is None:
            val_cache[key] = None
        else:
            m = masks[tou]
            diff = M[m, ki] - M[m, si]
            ok = ~np.isnan(diff)
            pay = np.maximum(diff, 0.0) if hedge == "OPT" else diff
            cal = cal_arr[m]
            per = {}
            for cm in range(1, 13):
                sel = ok & (cal == cm)
                if sel.sum() >= 100:
                    per[cm] = float(pay[sel].mean())
            med = float(np.median(list(per.values()))) if per else None
            val_cache[key] = {"per": per, "med": med}
    v = val_cache[key]
    if v is None or v["med"] is None:
        return None
    return v["per"].get(cal_month, v["med"])

today = dt.date(2026, 9, 1)
holders = collections.defaultdict(lambda: {"mw": 0.0, "mark": 0.0, "stale_mw": 0.0,
                                           "stale_mark": 0.0, "n": 0, "stale_paths": set()})
unmarked = 0
for holder, src, snk, tou, hedge, start, end, mw in live:
    mwf = float(mw or 0)
    mark = 0.0; ok = True
    m0 = max(start, today)
    y, mo = m0.year, m0.month
    while (y, mo) <= (end.year, end.month):
        v = month_value(src, snk, tou, hedge, mo)
        if v is None:
            ok = False; break
        mark += mwf * hours_in(y, mo, tou) * v
        mo += 1
        if mo == 13: mo, y = 1, y + 1
    if not ok:
        unmarked += 1; continue
    h = holders[holder]
    h["mw"] += mwf; h["mark"] += mark; h["n"] += 1
    s = stale_nodes.get(src) or stale_nodes.get(snk)
    if s:
        h["stale_mw"] += mwf; h["stale_mark"] += mark
        h["stale_paths"].add(f"{src}->{snk} ({s})")

print(f"marked {sum(h['n'] for h in holders.values()):,} groups; unmarked (no price history): {unmarked:,}")
out = sorted(holders.items(), key=lambda kv: -abs(kv[1]["stale_mark"]))
import csv as _csv
tgt = pathlib.Path.home() / "Downloads" / "target_list.csv"
with tgt.open("w", newline="") as fh:
    w = _csv.writer(fh)
    w.writerow(["holder", "positions", "mw", "mark_$", "stale_mw", "stale_mark_$", "sample_stale_paths"])
    for hname, h in out[:40]:
        w.writerow([hname, h["n"], round(h["mw"]), round(h["mark"]), round(h["stale_mw"]),
                    round(h["stale_mark"]), "; ".join(sorted(h["stale_paths"])[:3])])
print(f"wrote {tgt}")
print(f"\nTOP 12 OUTREACH TARGETS (by $ of marked value sitting on stale constraints)")
print(f"{'holder':<10}{'positions':>10}{'MW':>10}{'mark $':>14}{'stale MW':>10}{'stale mark $':>14}")
for hname, h in out[:12]:
    print(f"{hname:<10}{h['n']:>10,}{h['mw']:>10,.0f}{h['mark']:>14,.0f}{h['stale_mw']:>10,.0f}{h['stale_mark']:>14,.0f}")
json.dump({k: {kk: (sorted(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()}
           for k, v in holders.items()}, open(REF / "holder_marks.json", "w"))
print("wrote", REF / "holder_marks.json")
