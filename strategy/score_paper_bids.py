"""Score stored paper bids — the honest look-back.

Phase 1 (run after the auction's MarketResults are ingested):
    fills clearing_price and cleared (bid limit >= clearing price on that
    path/TOU/hedge in that auction).
Phase 2 (run after the delivery month's DAM prices are in the archive cache):
    fills realized_value ($/MW over the TOU block) and pnl for cleared bids
    (pay the CLEARING price, not the bid — uniform-price auction).

Usage:
    python strategy/score_paper_bids.py 2026-09-monthly-steve-1
"""
import collections
import datetime as dt
import json
import os
import sys

import psycopg

CACHE = os.path.expanduser("~/ercotcron-archive/cache")
MON = {1:'jan',2:'feb',3:'mar',4:'apr',5:'may',6:'jun',7:'jul',8:'aug',9:'sep',10:'oct',11:'nov',12:'dec'}
HOLS = {dt.date(2026,1,1),dt.date(2026,5,25),dt.date(2026,7,3),dt.date(2026,9,7),dt.date(2026,11,26),dt.date(2026,12,25),
        dt.date(2027,1,1),dt.date(2027,5,31),dt.date(2027,7,5),dt.date(2027,9,6),dt.date(2027,11,25),dt.date(2027,12,24)}

def tou_of(d, he):
    wk = d.weekday() >= 5 or d in HOLS
    return ('PeakWE' if wk else 'PeakWD') if 7 <= he <= 22 else 'Off-peak'

def month_of(auction_name):
    m = auction_name[:3].upper()
    return dict(JAN=1,FEB=2,MAR=3,APR=4,MAY=5,JUN=6,JUL=7,AUG=8,SEP=9,OCT=10,NOV=11,DEC=12)[m], int(auction_name[3:7])

batch = sys.argv[1]
with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
    c.execute("set statement_timeout=0")
    cur = c.cursor()
    cur.execute("select auction_name, source, sink, time_of_use, hedge_type, mw, bid_price, cleared from paper_bids where batch_id=%s", (batch,))
    bids = cur.fetchall()
    if not bids:
        sys.exit(f"no paper bids stored for batch {batch}")
    auction = bids[0][0]
    mo, yr = month_of(auction)

    # Phase 1: clearing prices from ingested auction results
    cur.execute("""select source, sink, time_of_use, hedge_type, avg(clearing_price)
                     from crr_awards where auction_name=%s group by 1,2,3,4""", (auction,))
    clears = {tuple(r[:4]): float(r[4]) for r in cur.fetchall()}
    if clears:
        n_clr = 0
        for _, src, snk, tou, hedge, mw, bid, _ in bids:
            cp = clears.get((src, snk, tou, hedge))
            cleared = cp is not None and float(bid) >= cp
            n_clr += bool(cleared)
            cur.execute("""update paper_bids set clearing_price=%s, cleared=%s, scored_at=now()
                            where batch_id=%s and source=%s and sink=%s and time_of_use=%s
                              and hedge_type=%s and mw=%s and bid_price=%s""",
                        (cp, cleared, batch, src, snk, tou, hedge, mw, bid))
        c.commit()
        print(f"phase 1: {auction} results in — {n_clr}/{len(bids)} bids would have cleared")
    else:
        print(f"phase 1 pending: {auction} results not ingested yet")

    # Phase 2: realized payoff from the archive DAM cache
    tag = f"{MON[mo]}{str(yr)[2:]}"
    path = f"{CACHE}/dam_{tag}.json"
    if os.path.exists(path):
        idx = collections.defaultdict(dict)
        for r in json.load(open(path)):
            idx[(r["delivery_date"], r["hour_ending"])][r["settlement_point"]] = r["price"]
        total = 0.0
        for _, src, snk, tou, hedge, mw, bid, _ in bids:
            cp = clears.get((src, snk, tou, hedge))
            if cp is None or float(bid) < cp:
                continue
            rv = 0.0; hrs = 0
            for (d, he), pp in idx.items():
                if src in pp and snk in pp and tou_of(dt.date.fromisoformat(d), he) == (tou if tou != 'Off-Peak' else 'Off-peak'):
                    diff = pp[snk] - pp[src]
                    if hedge == 'OPT':
                        diff = max(0.0, diff)
                    rv += diff; hrs += 1
            pnl = (rv - cp * hrs) * float(mw)
            total += pnl
            cur.execute("""update paper_bids set realized_value=%s, pnl=%s, scored_at=now()
                            where batch_id=%s and source=%s and sink=%s and time_of_use=%s
                              and hedge_type=%s and mw=%s and bid_price=%s""",
                        (rv, pnl, batch, src, snk, tou, hedge, mw, bid))
        c.commit()
        print(f"phase 2: settled — batch paper P&L ${total:,.2f}")
    else:
        print(f"phase 2 pending: no DAM cache for {tag} yet")
