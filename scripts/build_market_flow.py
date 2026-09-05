#!/usr/bin/env python3
"""Build the market-flow chart data: every monthly-auction path as a faint
strand, price-bucket aggregates as highlighted lines.

    python scripts/build_market_flow.py

The chart (landing page + Scorecard) shows cumulative return per $1 bid,
month after month, for every path the monthly auctions cleared — the whole
population as a dim field, five clearing-price buckets as labeled lines.
Strands are PATHS (public data, anonymous); nothing here maps to a holder,
satisfying the Scorecard aggregation rules (methodology §10).

Reads DAM prices from the local month caches (same loader convention as
market_scan.py — missing months auto-pull from dam_spp once) and awards from
crr_awards via a server-side cursor. Writes public/market_flow.json and the
same payload to the artifacts table as 'market_flow'.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import pathlib
import random
import time

import numpy as np
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg  # noqa: E402

CACHES = [pathlib.Path.home() / "ercotcron-archive" / "cache", pathlib.Path("/tmp")]

# Delivery months charted: every settled month with a monthly auction whose
# prices we cache. Sep-2024 through Aug-2026 (Aug is settled; Sep-2026 is
# mid-delivery and excluded — the chart is historical description only).
MONTH_TAGS = ["sep24", "oct24", "nov24", "dec24", "jan25", "feb25", "mar25",
              "apr25", "may25", "jun25", "jul25", "aug25", "sep25", "oct25",
              "nov25", "dec25", "jan26", "feb26", "mar26", "apr26", "may26",
              "jun26", "jul26", "aug26"]
MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
       "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MONNAME = {v: k.upper() for k, v in MON.items()}

# Clearing-price buckets — the whole-market study's bands. Label carries the
# class result; the chart recomputes the exact numbers from this data.
BUCKETS = [
    (0.0, 0.10, "under 10¢"),
    (0.10, 0.75, "10–75¢"),
    (0.75, 2.0, "75¢–$2"),
    (2.0, 5.0, "$2–$5"),
    (5.0, float("inf"), "over $5"),
]
MAX_STRANDS = 2000          # sampled for rendering; aggregates use everything
MIN_MONTHS_FOR_STRAND = 4   # a strand needs a visible trajectory


def tou_of(d: dt.date, he: int) -> str:
    if not (7 <= he <= 22):
        return "Off-peak"
    return "PeakWD" if d.weekday() < 5 else "PeakWE"


def load_month(tag: str) -> dict:
    path = next((d / f"dam_{tag}.json" for d in CACHES if (d / f"dam_{tag}.json").exists()), None)
    if path is None:
        mon, yr = MON[tag[:3]], 2000 + int(tag[3:])
        lo = dt.date(yr, mon, 1)
        hi = dt.date(yr + (mon == 12), (mon % 12) + 1, 1)
        print(f"  {tag}: pulling from dam_spp ({lo}..{hi})...", flush=True)
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as cdb:
            cdb.execute("set statement_timeout='15min'")
            cur = cdb.cursor()
            cur.execute("""select settlement_point, delivery_date::text, hour_ending, price
                             from dam_spp where delivery_date >= %s and delivery_date < %s""",
                        (lo, hi))
            rows = [{"settlement_point": r[0], "delivery_date": r[1],
                     "hour_ending": r[2], "price": float(r[3])} for r in cur.fetchall()]
        (CACHES[0] / f"dam_{tag}.json").write_text(json.dumps(rows))
    else:
        rows = json.loads(path.read_text())
    return rows


def main() -> int:
    t0 = time.time()
    random.seed(7)

    # ---- awards: per path, per monthly auction (streamed once, cached)
    aw_cache = CACHES[0] / "monthly_awards_by_auction.json"
    if aw_cache.exists():
        awards = json.loads(aw_cache.read_text())
    else:
        print("streaming monthly awards from crr_awards...", flush=True)
        awards = []
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
            c.execute("set statement_timeout='30min'")
            with c.cursor(name="flow_awards") as scur:
                scur.itersize = 20000
                scur.execute("""
                    select auction_name, source, sink, time_of_use, hedge_type,
                           avg(clearing_price), sum(mw)
                      from crr_awards where auction_name like '%%Monthly'
                      group by 1,2,3,4,5""")
                for a, s, k, t, h, cp, mw in scur:
                    awards.append([a, s, k, t, h, float(cp), float(mw or 0)])
        aw_cache.write_text(json.dumps(awards))
    print(f"awards rows: {len(awards):,}", flush=True)

    by_auction: dict[str, list] = collections.defaultdict(list)
    for a, s, k, t, h, cp, mw in awards:
        by_auction[a].append((s, k, t, h, cp, mw))

    months: list[str] = []
    # path key -> {month_index: (roi, cp, mw)}
    path_months: dict[tuple, dict[int, tuple]] = collections.defaultdict(dict)

    for tag in MONTH_TAGS:
        mon, yr = MON[tag[:3]], 2000 + int(tag[3:])
        auction = f"{MONNAME[mon]}{yr}Monthly"
        if auction not in by_auction:
            continue
        rows = load_month(tag)
        # matrix for this month
        point_idx: dict[str, int] = {}
        by_hour: dict[tuple, dict[int, float]] = collections.defaultdict(dict)
        for r in rows:
            i = point_idx.setdefault(r["settlement_point"], len(point_idx))
            by_hour[(r["delivery_date"], r["hour_ending"])][i] = float(r["price"])
        hour_keys = sorted(by_hour)
        M = np.full((len(hour_keys), len(point_idx)), np.nan, dtype=np.float32)
        for ri, hk in enumerate(hour_keys):
            for ci, price in by_hour[hk].items():
                M[ri, ci] = price
        tou_arr = np.array([tou_of(dt.date.fromisoformat(d), he) for d, he in hour_keys])
        masks = {t: tou_arr == t for t in ("Off-peak", "PeakWD", "PeakWE")}

        mi = len(months)
        months.append(f"{yr}-{mon:02d}")
        priced = 0
        for s, k, t, h, cp, mw in by_auction[auction]:
            si, ki = point_idx.get(s), point_idx.get(k)
            if si is None or ki is None or t not in masks or cp is None:
                continue
            diff = M[masks[t], ki] - M[masks[t], si]
            diff = diff[~np.isnan(diff)]
            if diff.size < 50:
                continue
            pay = np.maximum(diff, 0.0) if h == "OPT" else diff
            payoff = float(pay.mean())       # per MWh-hour, same basis as cp
            if cp <= 0.01:                   # sub-penny denominators are noise
                continue
            # Dollars, not ratios: everything downstream is "cumulative paid
            # out over cumulative paid in" — the only aggregation that can't
            # be distorted by penny denominators or summed-ratio drift, and
            # the same basis as the whole-market study.
            prem = cp * mw * diff.size
            paid = payoff * mw * diff.size
            path_months[(s, k, t, h)][mi] = (cp, prem, paid)
            priced += 1
        print(f"  {auction}: {priced:,} paths priced", flush=True)

    # ---- bucket aggregates: MW-weighted mean ROI per month, cumulative
    def bucket_of(cp: float) -> int:
        for bi, (lo, hi, _) in enumerate(BUCKETS):
            if lo <= cp < hi:
                return bi
        return len(BUCKETS) - 1

    bucket_month: dict[tuple[int, int], list] = collections.defaultdict(list)
    for key, mm in path_months.items():
        for mi, (cp, prem, paid) in mm.items():
            bucket_month[(bucket_of(cp), mi)].append((prem, paid))

    bucket_series = []
    for bi, (_lo, _hi, label) in enumerate(BUCKETS):
        cprem = cpaid = 0.0
        series, n_pos = [], 0
        for mi in range(len(months)):
            for prem, paid in bucket_month.get((bi, mi), []):
                cprem += prem
                cpaid += paid
                n_pos += 1
            series.append(round((cpaid - cprem) / cprem, 4) if cprem > 0 else 0.0)
        bucket_series.append({"label": label, "series": series, "paths": n_pos})

    # ---- strands: sampled paths, cumulative ROI where they held, carried flat
    # Sample = the biggest paths by total premium FIRST (so anything visible
    # on the grid map has a strand to link to), then random fill for texture.
    strands = []
    # The guaranteed head takes the biggest paths by premium even with short
    # histories (the grid map shows LIVE months, where new paths are common);
    # the random tail keeps the texture floor at MIN_MONTHS_FOR_STRAND.
    all_keys = list(path_months)
    prem_of = {k: sum(v[1] for v in path_months[k].values()) for k in all_keys}
    all_keys.sort(key=lambda k: -prem_of[k])
    head = all_keys[:1400]
    tail = [k for k in all_keys[1400:] if len(path_months[k]) >= MIN_MONTHS_FOR_STRAND]
    random.shuffle(tail)
    keys = head + tail
    for key in keys[:MAX_STRANDS]:
        mm = path_months[key]
        avg_cp = sum(v[0] for v in mm.values()) / len(mm)
        cprem = cpaid = 0.0
        ys = []
        cps = []   # the path's clearing price per auction month — "did it
                   # get pricier or cheaper over time" rides on this
        first = min(mm)
        for mi in range(len(months)):
            cps.append(round(mm[mi][0], 4) if mi in mm else None)
            if mi < first:
                ys.append(None)
                continue
            if mi in mm:
                cprem += mm[mi][1]
                cpaid += mm[mi][2]
            ys.append(round((cpaid - cprem) / cprem, 3) if cprem > 0 else 0.0)
        strands.append({"b": bucket_of(avg_cp), "y": ys, "c": cps,
                        "l": f"{key[0]} → {key[1]} · {key[2]} · {key[3]}",
                        "cp": round(avg_cp, 3)})

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "months": months,
        "buckets": bucket_series,
        "strands": strands,
        "n_paths": len(path_months),
        "note": ("Cumulative return per $1 bid, month after month, for every "
                 "path cleared in ERCOT monthly CRR auctions. Paths, never "
                 "holders. Historical description, not a forecast."),
    }
    out = ROOT / "public" / "market_flow.json"
    out.write_text(json.dumps(payload))
    print(f"wrote {out} ({out.stat().st_size/1e6:.1f} MB) — "
          f"{len(path_months):,} paths, {len(strands):,} strands, "
          f"{len(months)} months in {time.time()-t0:,.0f}s")

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        cur.execute("""insert into artifacts (name, body, updated_at)
                        values ('market_flow', %s, now())
                        on conflict (name) do update
                          set body = excluded.body, updated_at = now()""",
                    (json.dumps(payload),))
        c.commit()
    print("published artifact 'market_flow'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
