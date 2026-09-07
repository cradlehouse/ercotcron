"""The scoring pass: paper batches and sheet snapshots, graded daily.

Split out of products.py (which keeps the artifact builders) so the code that
GRADES the public record lives in one reviewable module. Same connection
pattern; scoring may run long, so the statement timeout stays off here.
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
import os

import psycopg

from ercot import ingest
from ercot.calendar import tou_of

log = logging.getLogger(__name__)


def _conn():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40)


def score_paper(_c=None) -> ingest.Result:
    """Daily: score open paper-bid batches — fills once auction results exist,
    P&L once the delivery month has settled prices in dam_spp."""
    res = ingest.Result()
    with _conn() as conn:
        conn.execute("set statement_timeout=0")
        cur = conn.cursor()
        # A batch stays in scope until every bid is fully scored: fills
        # pending, P&L pending on fills, OR realized_value pending on ANY bid
        # (all-miss batches used to drop out here and never got their
        # counterfactual — which quietly flattered the record).
        cur.execute("""select distinct batch_id, auction_name from paper_bids
                        where cleared is null or (cleared and pnl is null)
                           or realized_value is null""")
        batches = cur.fetchall()
        for batch, auction in batches:
            cur.execute("""select source, sink, time_of_use, hedge_type,
                                  avg(clearing_price), sum(mw)
                             from crr_awards where auction_name = %s group by 1,2,3,4""",
                        (auction,))
            award_rows = cur.fetchall()
            clears = {tuple(r[:4]): float(r[4]) for r in award_rows}
            awarded_mw = {tuple(r[:4]): float(r[5] or 0) for r in award_rows}
            if not clears:
                # Results not posted yet — OR the batch was stored under a
                # guessed auction name that will never match (the 2028 batch
                # risk). Make the wait visible instead of silent.
                cur.execute("select min(submitted_at) from paper_bids where batch_id = %s", (batch,))
                sub = (cur.fetchone() or [None])[0]
                log.warning("paper batch %s: no awards under auction_name=%r "
                            "(submitted %s) — results unposted or name mismatch",
                            batch, auction, sub)
                continue
            cur.execute("""select source, sink, time_of_use, hedge_type, mw, bid_price,
                                  cleared, delivery_month
                             from paper_bids where batch_id = %s""", (batch,))
            bids = cur.fetchall()
            n_clr = 0
            months = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7, AUG=8,
                          SEP=9, OCT=10, NOV=11, DEC=12)
            settled_cache: dict[dt.date, bool] = {}
            # One month-of-prices pull per (month, path) — bids that share a
            # path (OPT + OBL, several TOU blocks) reuse it instead of each
            # re-fetching the same ~1,400 rows (the review's N+1).
            pair_cache: dict[tuple, dict] = {}

            def month_window(delivery_month):
                # per-bid delivery_month wins (long-term strips span months);
                # monthly batches fall back to the MONYYYY auction-name parse
                if delivery_month is not None:
                    start = delivery_month.replace(day=1)
                else:
                    start = dt.date(int(auction[3:7]), months[auction[:3].upper()], 1)
                end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                return start, end

            def is_settled(start, end, src, snk):
                # Settled = the delivery month is OVER and dam_spp holds the
                # final delivery day for BOTH endpoints of this path. The old
                # ">1000 rows in month" proxy scored partial months (then the
                # requeue filter froze them) and passed on hub-only data that
                # contained neither endpoint.
                if end > dt.date.today():
                    return False
                key = (start, src, snk)
                if key not in settled_cache:
                    cur.execute("""select count(distinct settlement_point) from dam_spp
                                    where delivery_date = %s and settlement_point in (%s, %s)""",
                                (end - dt.timedelta(days=1), src, snk))
                    settled_cache[key] = (cur.fetchone() or [0])[0] == 2
                return settled_cache[key]

            for src, snk, tou, hedge, mwq, bid, _, dmonth in bids:
                month_start, month_end = month_window(dmonth)
                settled = is_settled(month_start, month_end, src, snk)
                in_delivery = (not settled) and month_start <= dt.date.today()
                cp = clears.get((src, snk, tou, hedge))
                did_clear = cp is not None and float(bid) >= cp
                n_clr += bool(did_clear)
                pnl = rv = None
                run_v = run_h = run_thru = None
                # realized value is computed for EVERY bid once the month
                # settles — fills get actual P&L; misses and no-trades keep
                # their realized_value so the look-back can show the win that
                # was passed up (or the ghost that never existed). While a
                # month is IN DELIVERY, the same sum lands in running_value
                # (per-MW, partial-month, display-only — never the score).
                if settled or in_delivery:
                    ck = (month_start, src, snk)
                    if ck not in pair_cache:
                        cur.execute("""select delivery_date, hour_ending, settlement_point, price
                                         from dam_spp
                                        where delivery_date >= %s and delivery_date < %s
                                          and settlement_point in (%s, %s)""",
                                    (month_start, month_end, src, snk))
                        bh: dict = collections.defaultdict(dict)
                        ld = None
                        for d, he, p, price in cur.fetchall():
                            bh[(d, he)][p] = float(price)
                            if ld is None or d > ld:
                                ld = d
                        pair_cache[ck] = {"by_hour": bh, "latest_day": ld}
                    by_hour = pair_cache[ck]["by_hour"]
                    latest_day = pair_cache[ck]["latest_day"]
                    tot = 0.0
                    hrs = 0
                    want = tou if tou != "Off-Peak" else "Off-peak"
                    for (d, he), pp in by_hour.items():
                        if src in pp and snk in pp and tou_of(d, he) == want:
                            diff = pp[snk] - pp[src]
                            if hedge == "OPT":
                                diff = max(0.0, diff)
                            tot += diff
                            hrs += 1
                    if in_delivery:
                        run_v, run_h, run_thru = tot, hrs, latest_day
                    if settled and hrs > 0:
                        rv = tot
                        if did_clear:
                            # Paper fills are capped at the MW the auction
                            # actually awarded on the path — a 5 MW paper fill
                            # on a path that traded 2 MW is fiction that would
                            # flatter the record.
                            eff = min(float(mwq), awarded_mw.get((src, snk, tou, hedge), float(mwq)))
                            pnl = (tot - cp * hrs) * eff
                cur.execute("""update paper_bids
                                  set clearing_price=%s, cleared=%s,
                                      realized_value=coalesce(%s, realized_value),
                                      pnl=coalesce(%s, pnl),
                                      running_value=coalesce(%s, running_value),
                                      running_hours=coalesce(%s, running_hours),
                                      marked_through=coalesce(%s, marked_through),
                                      scored_at=now()
                                where batch_id=%s and source=%s and sink=%s
                                  and time_of_use=%s and hedge_type=%s and mw=%s and bid_price=%s""",
                            (cp, did_clear, rv, pnl, run_v, run_h, run_thru,
                             batch, src, snk, tou, hedge, mwq, bid))
            conn.commit()
            res.rows_seen += len(bids)
            log.info("paper batch %s: %d/%d bids cleared (settled=%s)",
                     batch, n_clr, len(bids), settled)
    return res


def score_sheets(_c=None) -> ingest.Result:
    """Daily: score sheet SNAPSHOTS — the full-method counterfactual.

    Fills once the auction's results post (reference limit >= clearing);
    settlement once the delivery month completes, same basis as score_paper.
    Red rows carry suggested_mw 0 — they are scored AS IF 1 MW so the
    don't-bid calls are graded too (the admin page labels them per-MW).
    """
    res = ingest.Result()
    months = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7, AUG=8,
                  SEP=9, OCT=10, NOV=11, DEC=12)
    with _conn() as conn:
        conn.execute("set statement_timeout=0")
        cur = conn.cursor()
        cur.execute("""select distinct sheet from sheet_snapshots
                        where filled is null or (filled and pnl is null)
                           or realized is null""")
        for (sheet,) in cur.fetchall():
            # a '-reconstructed' vintage scores against its real auction
            auction = sheet.split('-')[0]
            cur.execute("""select source, sink, time_of_use, hedge_type, avg(clearing_price)
                             from crr_awards where auction_name = %s group by 1,2,3,4""",
                        (auction,))
            clears = {tuple(r[:4]): float(r[4]) for r in cur.fetchall()}
            if not clears:
                log.warning("sheet %s: no awards posted yet", sheet)
                continue
            start = dt.date(int(auction[3:7]), months[auction[:3].upper()], 1)
            end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
            month_over = end <= dt.date.today()
            cur.execute("""select id, source, sink, time_of_use, hedge_type,
                                  ref_limit, suggested_mw
                             from sheet_snapshots where sheet = %s
                              and (filled is null or realized is null)""", (sheet,))
            rows = cur.fetchall()
            hours_of = {}
            for rid, src, snk, tou, hedge, ref, mwq in rows:
                cp = clears.get((src, snk, tou, hedge))
                filled = cp is not None and ref is not None and float(ref) >= cp
                eff_mw = float(mwq or 0) or 1.0   # red rows: per-MW basis
                cost = rv = pnl = None
                hrs = None
                if cp is not None and month_over:
                    key = (src, snk, tou)
                    if key not in hours_of:
                        cur.execute("""
                            select count(*), coalesce(sum(k.price - s.price), 0),
                                   coalesce(sum(greatest(k.price - s.price, 0)), 0)
                              from dam_spp s
                              join dam_spp k on k.interval_start = s.interval_start
                             where s.settlement_point = %s and k.settlement_point = %s
                               and s.delivery_date >= %s and s.delivery_date < %s
                               and crr_time_of_use(s.delivery_date, s.hour_ending) = %s""",
                                    (src, snk, start, end, tou))
                        hours_of[key] = cur.fetchone()
                    n_h, obl_sum, opt_sum = hours_of[key]
                    if n_h and n_h > 0:
                        hrs = int(n_h)
                        pay = float(opt_sum if hedge == "OPT" else obl_sum)
                        rv = pay * eff_mw
                        if cp is not None:
                            cost = cp * hrs * eff_mw
                            if filled:
                                pnl = rv - cost
                cur.execute("""update sheet_snapshots
                                  set clearing=%s, filled=%s, hours=%s,
                                      cost=coalesce(%s, cost),
                                      realized=coalesce(%s, realized),
                                      pnl=coalesce(%s, pnl), scored_at=now()
                                where id=%s""",
                            (cp, filled, hrs, cost, rv, pnl, rid))
                res.rows_seen += 1
            conn.commit()
            log.info("sheet %s: %d rows scored (month_over=%s)", sheet, len(rows), month_over)
    return res


def score_all(c=None) -> ingest.Result:
    """The daily scoring pass: paper batches, then sheet snapshots."""
    a = score_paper(c)
    b = score_sheets(c)
    a.rows_seen += b.rows_seen
    return a
