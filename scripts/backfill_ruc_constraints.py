#!/usr/bin/env python3
"""Backfill RUC binding transmission constraints (NP5-755-CD).

    python scripts/backfill_ruc_constraints.py --days 365

RUC reruns commitment AFTER the DAM clears, on fresher load/wind forecasts.
Its binding constraints are ERCOT's own post-DAM constraint view — the event
signal between "DAM said" and "RT delivered". Files post per RUC run, so the
archive is dense; default window is 90 days to prove value before going deep.
"""
from __future__ import annotations

import argparse, csv, io, json, os, pathlib, sys, time, zipfile
import urllib.request
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from ercot.client import ErcotClient  # noqa: E402

DDL = """
create table if not exists ruc_constraints (
  delivery_date   date not null,
  hour_ending     int  not null,
  constraint_id   int  not null,
  constraint_name text not null,
  contingency     text not null default '',
  limit_mw        numeric,
  value_mw        numeric,
  violated_mw     numeric,
  shadow_price    numeric,
  from_station    text,
  to_station      text,
  from_kv         numeric,
  to_kv           numeric,
  ingested_at     timestamptz not null default now(),
  primary key (delivery_date, hour_ending, constraint_id, contingency)
);
create index if not exists ruc_constraints_name_idx on ruc_constraints (constraint_name);
alter table ruc_constraints enable row level security;
drop policy if exists ruc_constraints_read on ruc_constraints;
create policy ruc_constraints_read on ruc_constraints for select using (true);
grant select on ruc_constraints to anon, authenticated;
"""

INSERT = """
insert into ruc_constraints
  (delivery_date, hour_ending, constraint_id, constraint_name, contingency,
   limit_mw, value_mw, violated_mw, shadow_price,
   from_station, to_station, from_kv, to_kv)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
on conflict (delivery_date, hour_ending, constraint_id, contingency)
do update set shadow_price = excluded.shadow_price,
              limit_mw = excluded.limit_mw, value_mw = excluded.value_mw,
              violated_mw = excluded.violated_mw
"""


def num(s):
    try:
        return float(s) if s not in (None, "", " ") else None
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    client = ErcotClient()
    # Token must be re-read per request: it expires mid-run on long backfills
    # and a cached header silently turns into 401s partway through.
    def headers():
        return {"Authorization": f"Bearer {client.token()}",
                "Ocp-Apim-Subscription-Key": os.environ["ERCOT_SUBSCRIPTION_KEY"]}

    def raw(u, tries=5):
        for a in range(tries):
            try:
                req = urllib.request.Request(u, headers=headers())
                with urllib.request.urlopen(req, timeout=180) as r:
                    return r.read()
            except Exception:
                if a == tries - 1:
                    raise
                time.sleep(6 * (a + 1))

    # archive listing, newest first; keep everything within the window
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    docs, page = [], 1
    while True:
        d = json.loads(raw("https://api.ercot.com/api/public-reports/archive/"
                           f"NP5-755-CD?size=1000&page={page}"))
        arcs = d.get("archives") or []
        docs.extend(a for a in arcs
                    if datetime.fromisoformat(a["postDatetime"]).replace(tzinfo=timezone.utc) >= cutoff)
        if not arcs or datetime.fromisoformat(arcs[-1]["postDatetime"]).replace(tzinfo=timezone.utc) < cutoff:
            break
        page += 1
    print(f"daily files in window: {len(docs)}", flush=True)

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn:
        conn.execute("set statement_timeout='10min'")
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        total = 0
        for i, a in enumerate(reversed(docs)):        # oldest first, restart-friendly
            try:
                b = raw(a["_links"]["endpoint"]["href"])
                z = zipfile.ZipFile(io.BytesIO(b))
                txt = z.read(z.namelist()[0]).decode("utf8", "ignore")
            except Exception as exc:
                print(f"  [{i+1}/{len(docs)}] {a['postDatetime'][:10]} FAILED {str(exc)[:70]}", flush=True)
                continue
            rows = []
            for r in csv.DictReader(io.StringIO(txt)):
                try:
                    dd = datetime.strptime(r["DeliveryDate"].strip(), "%m/%d/%Y").date()
                    he = int(r["HourEnding"].split(":")[0])
                except (ValueError, KeyError):
                    continue
                rows.append((dd, he, int(num(r.get("ConstraintID")) or 0),
                             (r.get("ConstraintName") or "").strip(),
                             (r.get("ContingencyName") or "").strip(),
                             num(r.get("ConstraintLimit")), num(r.get("ConstraintValue")),
                             num(r.get("ViolationAmount")), num(r.get("ShadowPrice")),
                             (r.get("FromStation") or "").strip() or None,
                             (r.get("ToStation") or "").strip() or None,
                             num(r.get("FromStationkV")), num(r.get("ToStationkV"))))
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(INSERT, rows)
                conn.commit()
                total += len(rows)
            if (i + 1) % 25 == 0:
                print(f"  [{i+1}/{len(docs)}] total rows {total:,}", flush=True)
        with conn.cursor() as cur:
            cur.execute("select count(*), min(delivery_date), max(delivery_date) from ruc_constraints")
            print("\nruc_constraints:", cur.fetchone())
            cur.execute("""select constraint_name, count(*) n,
                                  round(avg(shadow_price)::numeric,1)
                             from ruc_constraints group by 1 order by n desc limit 8""")
            for r in cur.fetchall():
                print("   ", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
