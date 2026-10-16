#!/usr/bin/env python3
"""Check every paper month's inputs were published by its decision date.

    python strategy/input_audit.py

For each sealed month: the auction's bid window (from ERCOT market notices
where we have them, otherwise inferred as results-posting minus 7 days), and
the latest publication timestamp the database records for each input window
the builder read. Prints one row per month; a FAIL means an input was
published after the decision date.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg
from dotenv import load_dotenv

from strategy.common import ARCHIVE, ROOT
from strategy.paper_month import MON

load_dotenv(ROOT / ".env")

# bid-window close (17:00 CT) from ERCOT market notices M-E052926-01,
# M-A070226-01, M-E073126-01, M-B082826-01, M-B100226-01
NOTICE_CLOSE = {
    "2026-07": "2026-06-11",
    "2026-08": "2026-07-16",
    "2026-09": "2026-08-13",
    "2026-10": "2026-09-10",
    "2026-11": "2026-10-15",
}


def main() -> int:
    sealed = sorted(p for p in (ARCHIVE / "out" / "sealed").glob("paper_20*_PeakWD"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("set statement_timeout='300s'")
        posted = {
            a: f.split(".")[3][:8]
            for a, f in c.execute(
                "select auction_name, file_name from crr_auctions where report_type='monthly'"
            )
        }
        print(
            f"{'month':8s} {'asof':10s} {'bids close':12s} {'model built':11s} {'DAM discl.':>11s} {'DAM prices':>11s} {'outages':>10s} {'prior auctions':>15s}  verdict"
        )
        for d in sealed:
            man = json.loads((d / "manifest.json").read_text())
            ym, asof = man["delivery"], date.fromisoformat(man["asof"])
            y, m = map(int, ym.split("-"))
            res = posted.get(f"{MON[m - 1]}{y}Monthly")
            close = NOTICE_CLOSE.get(ym)
            close_s = (
                f"{close} N"
                if close
                else (
                    f"{(date(int(res[:4]), int(res[4:6]), int(res[6:8])) - timedelta(days=7))} i"
                    if res
                    else "?"
                )
            )
            an = man["analog"]
            rec = man.get("recent") or an
            disc = max(
                c.execute(
                    f"select max(source_posted_at)::date from {t} where delivery_date between %s and %s",
                    (lo, hi),
                ).fetchone()[0]
                or date.min
                for t in ("dam_virtual_awards", "dam_ptp_awards")
                for lo, hi in (an, rec)
            )
            hw = man["history_window"]
            spp = c.execute(
                "select max(posted_at)::date from dam_spp where delivery_date between %s and %s",
                (hw[0], hw[1]),
            ).fetchone()[0]
            outs = c.execute(
                "select max(report_date) from resource_outages where report_date <= %s", (asof,)
            ).fetchone()[0]
            pa = max(posted.get(a, "99999999") for a in man["prior_auctions"])
            built = man["model_built"]
            checks = [
                disc <= asof,
                spp is None or spp <= asof,
                outs <= asof,
                pa <= asof.strftime("%Y%m%d"),
                built <= asof.strftime("%Y%m%d"),
            ]
            print(
                f"{ym:8s} {asof!s:10s} {close_s:12s} {built:11s} {disc!s:>11s} {spp!s:>11s} {outs!s:>10s} {pa:>15s}  "
                f"{'ok' if all(checks) else 'FAIL'}{' (model ' + man.get('model_month', ym) + ')' if man.get('model_month', ym) != ym else ''}"
            )
    print(
        "bids close: N = ERCOT market notice, i = inferred (results posting - 7 days). DAM constraints carry no"
        " publication timestamp; they post the day before delivery and the window ends the day before asof."
    )
    print(
        "Model build date is from the RAW header; ERCOT protocol posts the CRR model at least 10 business days"
        " before the auction, which is before every asof here, but the posting timestamp itself is not recorded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
