"""Product builders that run ON the platform (Render), not on anyone's laptop.

Reads: reference artifacts (artifacts table) + market tables (dam_spp,
crr_awards, node_hourly_basis, path_valuations, paper_bids).
Writes: generated artifacts the web serves via /api/artifact/[name].
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import logging
import os

import psycopg

from ercot import ingest

log = logging.getLogger(__name__)

TOP_POINTS = 120
TOP_PATHS = 40
TOP_CONSTRAINTS = 25

HOLS = {dt.date(y, m, d) for (y, m, d) in [
    (2024,1,1),(2024,5,27),(2024,7,4),(2024,9,2),(2024,11,28),(2024,12,25),
    (2025,1,1),(2025,5,26),(2025,7,4),(2025,9,1),(2025,11,27),(2025,12,25),
    (2026,1,1),(2026,5,25),(2026,7,3),(2026,9,7),(2026,11,26),(2026,12,25),
    (2027,1,1),(2027,5,31),(2027,7,5),(2027,9,6),(2027,11,25),(2027,12,24),
    (2028,1,1),(2028,5,29),(2028,7,4),(2028,9,4),(2028,11,23),(2028,12,25),
]}


def tou_of(d: dt.date, he: int) -> str:
    wk = d.weekday() >= 5 or d in HOLS
    return ("PeakWE" if wk else "PeakWD") if 7 <= he <= 22 else "Off-peak"


def _conn():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40)


def load_artifact(cur, name: str):
    cur.execute("select body from artifacts where name = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def save_artifact(cur, name: str, body, built_by: str) -> None:
    cur.execute(
        """insert into artifacts (name, body, built_by) values (%s, %s, %s)
           on conflict (name) do update
             set body = excluded.body, updated_at = now(), built_by = excluded.built_by""",
        (name, json.dumps(body), built_by),
    )


# ------------------------------------------------------------------- graph --

TX = dict(lat=(25.6, 36.6), lon=(-107.0, -93.4))


def _in_tx(lat, lon):
    return TX["lat"][0] <= lat <= TX["lat"][1] and TX["lon"][0] <= lon <= TX["lon"][1]


def build_products(_c=None) -> ingest.Result:
    """Nightly: rebuild node_graph + grid_geo artifacts from DB + refs."""
    res = ingest.Result()
    with _conn() as conn:
        conn.execute("set statement_timeout=0")
        cur = conn.cursor()
        geo = load_artifact(cur, "ref/node_geo") or {}
        exp = load_artifact(cur, "ref/constraint_exposure") or {}
        stab_raw = load_artifact(cur, "ref/constraint_stability") or {}
        stab = {k: (v.get("binding_hours", 0) if isinstance(v, dict) else 0)
                for k, v in stab_raw.items()}
        v3 = load_artifact(cur, "ref/node_location_tiered_v3") or {}
        stations = load_artifact(cur, "ref/station_coords") or {}
        edges = (load_artifact(cur, "ref/nrg_topology_edges") or {}).get("edges", [])

        # live MW per point
        cur.execute("""
            with live as (select source, sink, mw from crr_awards where end_date >= now()::date)
            select p, sum(mw) from (
              select source p, mw from live union all select sink p, mw from live
            ) x group by 1 order by 2 desc limit %s""", (TOP_POINTS,))
        mw = {r[0]: float(r[1]) for r in cur.fetchall()}

        exp_nodes = list({e["node"] for v in exp.values() for e in v
                          if abs(e.get("beta", 0)) >= 0.03} - set(mw))
        if exp_nodes:
            cur.execute("""
                with live as (select source, sink, mw from crr_awards where end_date >= now()::date)
                select p, sum(mw) from (
                  select source p, mw from live union all select sink p, mw from live
                ) x where p = any(%s) group by 1 order by 2 desc limit 60""", (exp_nodes,))
            for r in cur.fetchall():
                mw[r[0]] = float(r[1])

        cur.execute("""select settlement_point, avg(abs(basis)) from node_hourly_basis
                        where settlement_point = any(%s) group by 1""", (list(mw),))
        dart = {r[0]: round(float(r[1]), 2) for r in cur.fetchall()}

        cur.execute("""select source, sink, sum(mw) from crr_awards
                        where end_date >= now()::date and source = any(%s) and sink = any(%s)
                        group by 1, 2 order by 3 desc limit %s""",
                    (list(mw), list(mw), TOP_PATHS))
        crr_links = [{"source": s, "target": t, "kind": "crr",
                      "value": round(float(v) ** 0.5 / 3, 1)} for s, t, v in cur.fetchall()]

        def in_map(entries):
            return [e for e in entries if e["node"] in mw and abs(e["beta"]) >= 0.02]

        ranked = sorted(exp.items(), key=lambda kv: (-len(in_map(kv[1])),
                                                     -stab.get(kv[0], 0)))[:TOP_CONSTRAINTS]
        cong, shared, seen = [], [], set()
        for cname, entries in ranked:
            inside = in_map(entries)
            if len(inside) < 2:
                continue
            pos = sorted((e for e in inside if e["beta"] > 0), key=lambda e: -e["beta"])
            neg = sorted((e for e in inside if e["beta"] < 0), key=lambda e: e["beta"])
            if pos and neg:
                pair = (neg[0]["node"], pos[0]["node"])
                if pair not in seen and pair[0] != pair[1]:
                    seen.add(pair)
                    cong.append({"source": pair[0], "target": pair[1], "kind": "congestion",
                                 "value": round(min(9, 2 + abs(pos[0]["beta"]) * 40), 1),
                                 "label": cname})
            side = pos if len(pos) >= 2 else neg
            for a, b in zip(side, side[1:3]):
                pair = tuple(sorted((a["node"], b["node"])))
                if pair[0] != pair[1] and pair not in seen:
                    seen.add(pair)
                    shared.append({"source": pair[0], "target": pair[1],
                                   "kind": "shareddrv", "value": 2, "label": cname})

        zones = collections.defaultdict(lambda: collections.defaultdict(list))
        for p, v in mw.items():
            g = geo.get(p, {})
            zone = (g.get("zone") or "OTHER").replace("LZ_", "")
            sub = g.get("substation") or p.split("_")[0]
            zones[zone][sub].append({"name": p, "mw": round(v), "dart": dart.get(p, 0)})
        tree = {"name": "ERCOT", "children": [
            {"name": z, "children": [
                {"name": s, "children": pts} for s, pts in sorted(subs.items())]}
            for z, subs in sorted(zones.items())]}

        save_artifact(cur, "node_graph",
                      {"tree": tree, "links": crr_links + cong + shared,
                       "asOf": dt.date.today().isoformat(), "points": len(mw)},
                      "products")

        # ---- geo layer ----
        loc = {k: (r["lat"], r["lon"]) for k, r in v3.items()
               if r.get("lat") and r.get("lon") and _in_tx(r["lat"], r["lon"])}
        nodes = [{"name": n, "lat": round(loc[n][0], 4), "lon": round(loc[n][1], 4),
                  "mw": mw[n], "tier": v3.get(n, {}).get("tier", "D")}
                 for n in mw if n in loc]
        grid = []
        for a, b in edges:
            ca, cb = stations.get(a), stations.get(b)
            if ca and cb and _in_tx(*ca) and _in_tx(*cb):
                grid.append([[round(ca[0], 4), round(ca[1], 4)],
                             [round(cb[0], 4), round(cb[1], 4)]])
        pos_map = {n["name"]: (n["lat"], n["lon"]) for n in nodes}
        crr_geo = [{"a": pos_map[l["source"]], "b": pos_map[l["target"]], "v": l["value"],
                    "label": f'{l["source"]} → {l["target"]}'}
                   for l in crr_links
                   if l["source"] in pos_map and l["target"] in pos_map]

        import re
        def cpos(cname):
            tokens = [t for t in re.split(r"[_\W]+", cname.upper()) if len(t) >= 4]
            hits = [stations[t] for t in tokens if t in stations]
            if not hits:
                hits = [stations[s] for s in stations
                        if len(s) >= 5 and any(s in t or t in s for t in tokens)][:2]
            if not hits:
                return None
            la = sum(h[0] for h in hits) / len(hits)
            lo = sum(h[1] for h in hits) / len(hits)
            return (round(la, 4), round(lo, 4)) if _in_tx(la, lo) else None

        cons = [{"name": c, "lat": p[0], "lon": p[1]}
                for c in exp if (p := cpos(c))]

        # Public artifact carries AGGREGATE layers only. A named holder's book
        # layer ("steve") shipped here once — a per-holder "My book" layer
        # belongs behind the claim gate, not in a world-readable artifact.
        paths = {}
        for scope, cond in [("market", "")]:
            cur.execute(f"""
                with m as (
                  select to_char(gs, 'YYYY-MM') mo, source, sink, sum(mw) mw
                    from crr_awards,
                         generate_series(date_trunc('month', start_date),
                                         date_trunc('month', end_date), '1 month') gs
                   where end_date >= now()::date {cond}
                   group by 1, 2, 3)
                select mo, source, sink, mw from (
                  select *, row_number() over (partition by mo order by mw desc) rn
                    from m) x where rn <= 300""")
            # Deep pool on purpose: most points have no public coordinates
            # (ERCOT publishes none), so only a fraction of any top-N is
            # drawable — a shallow pool left ~12 paths on a "whole market"
            # map. The client draws what it gets; locatability is the filter.
            by_mo: dict[str, list] = {}
            for mo, s, k, mwv in cur.fetchall():
                a, b = loc.get(s), loc.get(k)
                if a and b:
                    by_mo.setdefault(mo, []).append(
                        {"a": [round(a[0], 4), round(a[1], 4)],
                         "b": [round(b[0], 4), round(b[1], 4)],
                         "v": round(float(mwv) ** 0.5 / 3, 1),
                         "label": f"{s} → {k} ({round(float(mwv))} MW)"})
            paths[scope] = by_mo
        cur.execute("""select book, source, sink from path_valuations
                        where ceiling is not null order by ceiling desc limit 200""")
        sugg = []
        for book, s, k in cur.fetchall():
            a, b = loc.get(s), loc.get(k)
            if a and b:
                sugg.append({"a": [a[0], a[1]], "b": [b[0], b[1]], "v": 2.5,
                             "label": f"{s} → {k} [{book}]"})
        paths["suggestions"] = {"all": sugg}

        save_artifact(cur, "grid_geo",
                      {"nodes": nodes, "grid": grid, "crr": crr_geo,
                       "constraints": cons, "paths": paths,
                       "asOf": dt.date.today().isoformat()},
                      "products")
        conn.commit()
        res.rows_seen = len(mw) + len(grid)
    log.info("products rebuilt: %d points, %d grid edges", len(mw), len(grid))
    return res


# ------------------------------------------------------------ paper scoring --

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
                cp = clears.get((src, snk, tou, hedge))
                did_clear = cp is not None and float(bid) >= cp
                n_clr += bool(did_clear)
                pnl = rv = None
                # realized value is computed for EVERY bid once the month
                # settles — fills get actual P&L; misses and no-trades keep
                # their realized_value so the look-back can show the win that
                # was passed up (or the ghost that never existed)
                if settled:
                    cur.execute("""select delivery_date, hour_ending, settlement_point, price
                                     from dam_spp
                                    where delivery_date >= %s and delivery_date < %s
                                      and settlement_point in (%s, %s)""",
                                (month_start, month_end, src, snk))
                    by_hour: dict = collections.defaultdict(dict)
                    for d, he, p, price in cur.fetchall():
                        by_hour[(d, he)][p] = float(price)
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
                    if hrs > 0:
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
                                      pnl=coalesce(%s, pnl), scored_at=now()
                                where batch_id=%s and source=%s and sink=%s
                                  and time_of_use=%s and hedge_type=%s and mw=%s and bid_price=%s""",
                            (cp, did_clear, rv, pnl, batch, src, snk, tou, hedge, mwq, bid))
            conn.commit()
            res.rows_seen += len(bids)
            log.info("paper batch %s: %d/%d bids cleared (settled=%s)",
                     batch, n_clr, len(bids), settled)
    return res
