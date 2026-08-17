"""Strip-mode scan for the 2028 2nd-6 long-term auction (bids Aug 18-20).

Since NPRR1288 the long-term auction sells INDIVIDUAL months, so a "strip"
position is six monthly bids. For every path with 2028 clearing history:
per delivery month Jul..Dec 2028 —
  rate     calendar-month conditioned realized $/MWh (same model as marks)
  hours    exact TOU hours of that 2028 month (NERC holidays applied)
  clear    avg clearing price for THAT month in prior 2028 sequences
  ceiling  rate / 1.5 (the 50%-margin rule), floored vs materiality
Output: public/strip_2028.json for the /bids/strip page.
"""
import collections
import datetime as dt
import json
import os

import numpy as np
import psycopg

CACHE = os.path.expanduser("~/ercotcron-archive/cache")
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "strip_2028.json")
MONTHS = [7, 8, 9, 10, 11, 12]
TAGS = {7: ["jul26"], 8: ["aug25"], 9: ["sep24", "sep25"], 10: ["oct25"],
        11: ["nov24", "nov25"], 12: ["dec24", "dec25"]}
HOLS = {dt.date(2024,1,1),dt.date(2024,5,27),dt.date(2024,7,4),dt.date(2024,9,2),dt.date(2024,11,28),dt.date(2024,12,25),
        dt.date(2025,1,1),dt.date(2025,5,26),dt.date(2025,7,4),dt.date(2025,9,1),dt.date(2025,11,27),dt.date(2025,12,25),
        dt.date(2026,1,1),dt.date(2026,5,25),dt.date(2026,7,3),dt.date(2026,9,7),dt.date(2026,11,26),dt.date(2026,12,25),
        dt.date(2028,1,1),dt.date(2028,5,29),dt.date(2028,7,4),dt.date(2028,9,4),dt.date(2028,11,23),dt.date(2028,12,25)}
REQUIRED_MARGIN = 1.5
MATERIALITY = 0.05

def tou_of(d, he):
    wk = d.weekday() >= 5 or d in HOLS
    return ("PeakWE" if wk else "PeakWD") if 7 <= he <= 22 else "Off-peak"

def hours_2028(month):
    out = collections.Counter()
    d = dt.date(2028, month, 1)
    while d.month == month:
        for he in range(1, 25):
            out[tou_of(d, he)] += 1
        d += dt.timedelta(days=1)
    return dict(out)

# ---- realized rates per (path, tou, hedge, month) from caches ----
print("loading caches...", flush=True)
month_mats = {}   # month -> list of (M, idx, tou_arr)
for m, tags in TAGS.items():
    mats = []
    for tag in tags:
        f = f"{CACHE}/dam_{tag}.json"
        if not os.path.exists(f):
            continue
        rows = json.load(open(f))
        idx, by_hour = {}, collections.defaultdict(dict)
        for r in rows:
            i = idx.setdefault(r["settlement_point"], len(idx))
            by_hour[(r["delivery_date"], r["hour_ending"])][i] = r["price"]
        keys = list(by_hour)
        M = np.full((len(keys), len(idx)), np.nan, dtype=np.float32)
        for ri, k in enumerate(keys):
            for ci, v in by_hour[k].items():
                M[ri, ci] = v
        tou_arr = np.array([tou_of(dt.date.fromisoformat(d), he) for d, he in keys])
        mats.append((M, idx, tou_arr))
        print(f"  {tag}: {M.shape}", flush=True)
    month_mats[m] = mats

def rate(src, snk, tou, hedge, month):
    vals, n_samples = [], 0
    for M, idx, tou_arr in month_mats[month]:
        if src not in idx or snk not in idx:
            continue
        d = M[:, idx[snk]] - M[:, idx[src]]
        d = d[tou_arr == tou]
        d = d[~np.isnan(d)]
        if len(d) == 0:
            continue
        if hedge == "OPT":
            d = np.maximum(d, 0.0)
        vals.append(float(d.mean()))
        n_samples += 1
    if not vals:
        return None, 0
    return float(np.mean(vals)), n_samples

# ---- paths + per-month clears from prior 2028 sequences ----
print("loading 2028 clearing history...", flush=True)
with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
    c.execute("set statement_timeout=0")
    cur = c.cursor()
    cur.execute("""
        select source, sink, time_of_use, hedge_type,
               extract(month from start_date)::int mo,
               avg(clearing_price), sum(mw)
          from crr_awards
         where auction_name ilike '%%2028%%'
           and start_date >= '2028-07-01' and end_date <= '2028-12-31'
         group by 1,2,3,4,5""")
    clears = {}
    path_mw = collections.Counter()
    for s, k, tou, h, mo, cp, mw in cur.fetchall():
        clears[(s, k, tou, h, mo)] = float(cp) if cp is not None else None
        path_mw[(s, k, tou, h)] += float(mw)

paths = [p for p, _ in path_mw.most_common(800)]
print(f"{len(paths)} paths with 2028 history", flush=True)

hours = {m: hours_2028(m) for m in MONTHS}
rows_out = []
for s, k, tou, h in paths:
    months_out, total_ceiling_cost, total_worth, ok = {}, 0.0, 0.0, 0
    for m in MONTHS:
        r, n = rate(s, k, tou, h, m)
        cp = clears.get((s, k, tou, h, m))
        if r is None:
            months_out[m] = None
            continue
        ceil = max(r / REQUIRED_MARGIN, 0.0)
        hrs = hours[m].get(tou if tou != "Off-Peak" else "Off-peak", 0)
        months_out[m] = {
            "rate": round(r, 4), "samples": n, "clear": round(cp, 4) if cp is not None else None,
            "ceiling": round(ceil, 4), "hours": hrs,
            "margin": round(ceil / cp, 2) if cp and cp > 0 else None,
        }
        ok += 1
        total_worth += r * hrs
        total_ceiling_cost += ceil * hrs
    if ok == 0:
        continue
    rows_out.append({
        "source": s, "sink": k, "tou": tou, "hedge": h,
        "prior_mw": round(path_mw[(s, k, tou, h)], 1),
        "months": months_out,
        "strip_worth_per_mw": round(total_worth, 2),
        "strip_cost_at_ceiling_per_mw": round(total_ceiling_cost, 2),
    })

rows_out.sort(key=lambda r: -(r["strip_worth_per_mw"] - r["strip_cost_at_ceiling_per_mw"]))
out = {"auction": "2028.2nd6 (Jul-Dec 2028) long-term", "bids": "2026-08-18 to 2026-08-20",
       "generated": dt.date.today().isoformat(), "hours": hours,
       "materiality": MATERIALITY, "rows": rows_out[:400]}
json.dump(out, open(OUT, "w"))
print(f"wrote {OUT}: {len(rows_out[:400])} paths", flush=True)
