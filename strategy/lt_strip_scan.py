#!/usr/bin/env python3
"""Long-term strip sheet: 2027 1st-half, sequence 1 (bids Oct 20-22, 2026).

    python strategy/lt_strip_scan.py [--freeze]
    python strategy/lt_strip_scan.py --year 2026 --grade   # backtest: the same
        rule as of Oct 2025, graded on the 2026 1st-6 Seq1 clears and the
        Jan-Jun 2026 settlement (one seasonal year only: DAM starts Jul 2024)

The last and deepest long-term sale of Jan-Jun 2027 delivery. Since
NPRR1288 the long-term auction sells individual months, so the sheet is one
row per (path, TOU, hedge, delivery month). Methodology v1.3, adapted to a
six-month strip:

  value_m   the WORSE of the two prior same-calendar months (2025-m, 2026-m).
            Two samples cannot carry a median; "paid at least this much both
            times" is the strip analogue of the typical-month cap — a
            one-year spike cannot set the price, a real seasonal edge (April,
            maintenance season, best month both years) survives.
  fade      path-level, strategy/valuation.py: fit Oct 2025-Jul 2026, tail
            Aug-Sep 2026 (held out; may only REMOVE a path).
  clear_m   the path's single-month clear for month m in the most recent
            prior 2027 1st-6 sequence that traded it (Seq2 first).
  limit_m   value_m / 1.5, lottery-capped under 50c clears; kept only when it
            beats clear_m, value_m beats clear_m by >= 10c, clear_m >= 5c,
            and >= 2 prior sequences priced the path-month.
  size      half the path-month's average BUY award per prior sequence,
            capped at 25 MW — the depth the market has actually supplied.

Also marks the design partner's existing 2027 1st-6 awards month by month
on the same value_m (--book HOLDER_PREFIX), the valuer-lane wind-down mark.

Outputs go to the private archive (never public/, never a public artifact —
the repo and /api/artifact are public). --freeze writes the sheet to
paper_bids as an append-only pre-registered batch, graded by score_paper.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import os
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
import psycopg

from ercot.calendar import tou_of
from strategy.common import CACHES, OUT
from strategy.valuation import value_months

MONTHS = [1, 2, 3, 4, 5, 6]
MARGIN, MATERIALITY, MAX_MW = 1.5, 0.05, 25
_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def ym_tag(ym: str) -> str:
    y, m = ym.split("-")
    return f"{_MON[int(m) - 1]}{y[2:]}"


def hours(year: int, month: int) -> dict[str, int]:
    out: collections.Counter = collections.Counter()
    d = dt.date(year, month, 1)
    while d.month == month:
        for he in range(1, 25):
            out[tou_of(d, he)] += 1
        d += dt.timedelta(days=1)
    return dict(out)


def load_month(ym: str) -> list[dict]:
    tag = ym_tag(ym)
    path = next((d / f"dam_{tag}.json" for d in CACHES if (d / f"dam_{tag}.json").exists()), None)
    if path is not None:
        return json.loads(path.read_text())
    lo = dt.date.fromisoformat(f"{ym}-01")
    hi = (lo + dt.timedelta(days=32)).replace(day=1)
    print(f"  {tag}: pulling from dam_spp ({lo}..{hi})...", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        c.execute("set statement_timeout='10min'")
        cur = c.cursor()
        cur.execute("""select settlement_point, delivery_date::text, hour_ending, price
                         from dam_spp where delivery_date >= %s and delivery_date < %s""", (lo, hi))
        rows = [{"settlement_point": r[0], "delivery_date": r[1], "hour_ending": r[2],
                 "price": float(r[3])} for r in cur.fetchall()]
    (CACHES[0] / f"dam_{tag}.json").write_text(json.dumps(rows))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true", help="write the sheet to paper_bids (append-only)")
    ap.add_argument("--book", default="XSAAI", help="holder-code prefix whose 1st-6 awards to mark")
    ap.add_argument("--year", type=int, default=2027, help="delivery year of the 1st-6 strip")
    ap.add_argument("--grade", action="store_true", help="backtest: grade against Seq1 clears + settlement")
    args = ap.parse_args()
    YEAR = args.year
    AUCTION = f"{YEAR}1st6AnnualAuctionSeq1"
    PRIOR = f"{YEAR}1st6AnnualAuctionSeq%"
    BATCH = f"{YEAR}-1st6-seq1-shadowprice-1"
    FIT = [f"{YEAR - 2}-{m:02d}" for m in (10, 11, 12)] + [f"{YEAR - 1}-{m:02d}" for m in range(1, 8)]
    TAIL = [f"{YEAR - 1}-08", f"{YEAR - 1}-09"]
    # same-calendar-month history; months before the archive (Jul 2024) drop out
    seasonal = {m: [f"{y}-{m:02d}" for y in (YEAR - 2, YEAR - 1) if f"{y}-{m:02d}" >= "2024-07"]
                for m in MONTHS}
    settle = [f"{YEAR}-{m:02d}" for m in MONTHS] if args.grade else []
    need = sorted(set(FIT + TAIL + settle + [ym for v in seasonal.values() for ym in v]))

    # ---- 1. price matrix
    print("loading DAM months...", flush=True)
    point_idx: dict[str, int] = {}
    keys: list[tuple[dt.date, int]] = []
    cols: list[dict[int, float]] = []
    for ym in need:
        by_hour: dict = collections.defaultdict(dict)
        for r in load_month(ym):
            i = point_idx.setdefault(r["settlement_point"], len(point_idx))
            by_hour[(r["delivery_date"], r["hour_ending"])][i] = float(r["price"])
        for (ds, he), pr in by_hour.items():
            keys.append((dt.date.fromisoformat(ds), he))
            cols.append(pr)
        print(f"  {ym}: +{len(by_hour):,} hours", flush=True)
    M = np.full((len(keys), len(point_idx)), np.nan, dtype=np.float32)
    for ri, pr in enumerate(cols):
        for ci, v in pr.items():
            M[ri, ci] = v
    tou_arr = np.array([tou_of(d, he) for d, he in keys])
    ym_arr = np.array([f"{d:%Y-%m}" for d, _ in keys])
    print(f"matrix {M.shape[0]:,} hours x {M.shape[1]:,} points", flush=True)

    def monthly(src: str, snk: str, tou: str, hedge: str) -> dict[str, float] | None:
        si, ki = point_idx.get(src), point_idx.get(snk)
        if si is None or ki is None:
            return None
        mask = tou_arr == tou
        d = M[mask, ki] - M[mask, si]
        if hedge == "OPT":
            d = np.where(np.isnan(d), np.nan, np.maximum(d, 0.0))
        yms = ym_arr[mask]
        out = {}
        for ym in need:
            sel = d[yms == ym]
            sel = sel[~np.isnan(sel)]
            if sel.size >= 40:          # a PeakWE month has ~144-160 hours
                out[ym] = float(sel.mean())
        return out

    # ---- 2. prior-sequence clears and depth, single-month rows only
    print(f"loading prior {YEAR} 1st-6 sequences...", flush=True)
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        c.execute("set statement_timeout='20min'")
        cur = c.cursor()
        cur.execute("""
            select source, sink, time_of_use, hedge_type,
                   extract(month from start_date)::int, auction_name,
                   coalesce(avg(clearing_price) filter (where not bid24hour), avg(clearing_price)),
                   sum(mw) filter (where bid_type = 'BUY')
              from crr_awards
             where auction_name like %s and auction_name <> %s
               and date_trunc('month', start_date) = date_trunc('month', end_date)
             group by 1,2,3,4,5,6""", (PRIOR, AUCTION))
        hist: dict = collections.defaultdict(list)
        for s, k, t, h, mo, auc, cp, mw in cur.fetchall():
            if cp is None:
                continue
            hist[(s, k, t, h, mo)].append((int(auc.rsplit("Seq", 1)[1]), float(cp), float(mw or 0)))
        cur.execute("""
            select account_holder, source, sink, time_of_use, hedge_type,
                   start_date, end_date, bid_type, sum(mw),
                   coalesce(avg(clearing_price) filter (where not bid24hour), avg(clearing_price)),
                   auction_name
              from crr_awards
             where auction_name like %s and auction_name <> %s and account_holder like %s
             group by 1,2,3,4,5,6,7,8,11""", (PRIOR, AUCTION, args.book + "%"))
        book = cur.fetchall() if not args.grade else []
        seq1 = {}
        if args.grade:
            cur.execute("""
                select source, sink, time_of_use, hedge_type, extract(month from start_date)::int,
                       coalesce(avg(clearing_price) filter (where not bid24hour), avg(clearing_price))
                  from crr_awards
                 where auction_name = %s
                   and date_trunc('month', start_date) = date_trunc('month', end_date)
                 group by 1,2,3,4,5""", (AUCTION,))
            seq1 = {tuple(r[:5]): float(r[5]) for r in cur.fetchall() if r[5] is not None}
    print(f"{len(hist):,} path-months priced in prior sequences; {len(book)} book rows", flush=True)

    # ---- 3. value every path-month
    hrs = {m: hours(YEAR, m) for m in MONTHS}
    paths = sorted({k[:4] for k in hist})
    cache: dict = {}
    sheet, faded_paths, drops = [], set(), collections.Counter()
    for p in paths:
        mm = cache.setdefault(p, monthly(*p))
        if not mm:
            drops["no prices"] += 1
            continue
        v = value_months([mm[ym] for ym in FIT if ym in mm], [mm[ym] for ym in TAIL if ym in mm])
        if v is None:
            drops["under 6 fitted months"] += 1
            continue
        if v.fading:
            faded_paths.add(p)
            drops["fading"] += 1
            continue
        for m in MONTHS:
            seqs = sorted(hist.get((*p, m), []))
            if len(seqs) < 2:
                continue
            ss = [mm.get(ym) for ym in seasonal[m]]
            if not ss or any(x is None for x in ss):
                continue
            value = min(ss)
            clear = seqs[0][1]                      # lowest Seq number = most recent sale
            if value <= 0 or clear < MATERIALITY or value - clear < 0.10:
                continue
            limit = value / MARGIN
            if clear < 0.5:
                limit = min(limit, max(3 * clear, 0.1))
            if limit <= clear:
                continue
            depth = float(np.mean([s[2] for s in seqs]))
            mw = int(max(1, min(MAX_MW, depth // 2)))
            h = hrs[m].get(p[2], 0)
            sheet.append({
                "source": p[0], "sink": p[1], "tou": p[2], "hedge": p[3], "month": m,
                "value": round(value, 4), "value_by_year": [round(x, 4) for x in ss],
                "clear": round(clear, 4), "limit": round(limit, 4), "margin": round(limit / clear, 2),
                "prior_seqs": len(seqs), "depth_mw": round(depth, 1), "mw": mw, "hours": h,
                "cost_at_clear": round(clear * h * mw, 0), "cost_at_limit": round(limit * h * mw, 0),
                "worth": round(value * h * mw, 0),
                "typical_month": round(v.median_month, 4),
                "tail": [round(mm[ym], 3) for ym in TAIL if ym in mm],
            })
    sheet.sort(key=lambda r: -(r["worth"] - r["cost_at_clear"]))
    print(f"\nsheet: {len(sheet)} path-months on {len({(r['source'], r['sink'], r['tou'], r['hedge']) for r in sheet})} paths;"
          f" dropped {dict(drops)}")
    by_m = collections.Counter(r["month"] for r in sheet)
    print("by month:", {m: by_m[m] for m in MONTHS},
          "| OBL share:", f"{sum(r['hedge'] == 'OBL' for r in sheet) / max(len(sheet), 1):.0%}")
    print(f"at suggested size: cost at clear ${sum(r['cost_at_clear'] for r in sheet):,.0f}, "
          f"at limit ${sum(r['cost_at_limit'] for r in sheet):,.0f}, worth ${sum(r['worth'] for r in sheet):,.0f}")

    # ---- 4. mark the existing book, month by month on the same value_m
    marked = []
    for holder, s, k, t, h, start, end, side, mw, cp, auc in book:
        p = (s, k, t, h)
        mm = cache.setdefault(p, monthly(*p)) or {}
        v = value_months([mm[ym] for ym in FIT if ym in mm], [mm[ym] for ym in TAIL if ym in mm])
        months_in = [m for m in MONTHS if start.month <= m <= end.month]
        worth = paid = 0.0
        unpriced = 0
        for m in months_in:
            ss = [mm.get(ym) for ym in seasonal[m]]
            hh = hrs[m].get(t, 0)
            paid += float(cp or 0) * hh * float(mw)
            if not ss or any(x is None for x in ss):
                unpriced += 1
                continue
            worth += min(ss) * hh * float(mw)
        sign = -1 if side == "SELL" else 1
        marked.append({
            "holder": holder, "auction": auc, "side": side, "source": s, "sink": k, "tou": t, "hedge": h,
            "window": f"{start:%b}-{end:%b} {YEAR}", "mw": float(mw), "clear": round(float(cp or 0), 4),
            "paid": round(sign * paid, 0), "worth_worse_year": round(sign * worth, 0),
            "fading": bool(v and v.fading), "months_unpriced": unpriced,
        })
    if marked:
        tp, tw = sum(r["paid"] for r in marked), sum(r["worth_worse_year"] for r in marked)
        print(f"\nbook ({args.book}*): {len(marked)} award rows, paid ${tp:,.0f}, worth on the worse-year "
              f"basis ${tw:,.0f}; {sum(r['fading'] for r in marked)} rows on fading paths")

    # ---- 4b. backtest grading: fill at Seq1, settle on the delivery month
    if args.grade:
        g = collections.defaultdict(float)
        n_fill = n_traded = wins = 0
        for r in sheet:
            p = (r["source"], r["sink"], r["tou"], r["hedge"])
            cp = seq1.get((*p, r["month"]))
            if cp is None:
                continue
            n_traded += 1
            paid = cache[p].get(f"{YEAR}-{r['month']:02d}")
            if paid is None:
                continue
            h, mw = r["hours"], r["mw"]
            g["mkt_cost"] += cp * h * mw
            g["mkt_paid"] += paid * h * mw
            if r["limit"] >= cp:
                n_fill += 1
                g["cost"] += cp * h * mw
                g["paid"] += paid * h * mw
                wins += paid > cp
                g[f"pnl_m{r['month']}"] += (paid - cp) * h * mw
        print(f"\nBACKTEST {AUCTION}: {len(sheet)} sheet rows, {n_traded} traded at Seq1, {n_fill} filled "
              f"({wins} paid more than they cost)")
        if g["cost"]:
            print(f"  filled: cost ${g['cost']:,.0f}  paid ${g['paid']:,.0f}  net ${g['paid'] - g['cost']:+,.0f}"
                  f"  ({g['paid'] / g['cost']:.0%} of cost)")
            print("  by month:", {m: round(g[f'pnl_m{m}']) for m in MONTHS})
        if g["mkt_cost"]:
            print(f"  all traded sheet rows at Seq1 clear: cost ${g['mkt_cost']:,.0f} paid ${g['mkt_paid']:,.0f}"
                  f" ({g['mkt_paid'] / g['mkt_cost']:.0%})")

    # ---- 5. private outputs
    out = OUT / f"lt_{YEAR}_1st6"
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    (out / f"sheet-{stamp}.json").write_text(json.dumps(sheet))
    (out / f"book-mark-{stamp}.json").write_text(json.dumps(marked, default=str))
    with open(out / f"sheet-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sheet[0]) if sheet else ["source"])
        w.writeheader()
        for r in sheet:
            w.writerow({**r, "tail": "/".join(str(x) for x in r["tail"])})
    print(f"wrote {out}/sheet-{stamp}.json (+csv) and book-mark-{stamp}.json")

    if args.freeze and not args.grade:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
            cur = c.cursor()
            n = cur.execute("select count(*) from paper_bids where batch_id = %s", (BATCH,)).fetchone()[0]
            if n:
                print(f"{BATCH} already frozen ({n} rows) — the register does not re-cut")
                return 1
            cur.executemany("""
                insert into paper_bids (batch_id, auction_name, source, sink, time_of_use,
                                        hedge_type, mw, bid_price, delivery_month)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(BATCH, AUCTION, r["source"], r["sink"], r["tou"], r["hedge"], r["mw"],
                  r["limit"], dt.date(YEAR, r["month"], 1)) for r in sheet])
            c.commit()
        print(f"froze {len(sheet)} bids as paper batch {BATCH} against {AUCTION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
