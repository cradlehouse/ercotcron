#!/usr/bin/env python3
"""Run one ingest job from the command line.

Used for the first seed pull, for repairing a gap, and by anything that wants a
job run without going through the service.

    python scripts/run_ingest.py dam
    python scripts/run_ingest.py lmp5 --since-minutes 720
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ercot import db, ingest  # noqa: E402
from ercot.jobs import JOBS, client, run_job  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=sorted(JOBS), help="job to run")
    parser.add_argument(
        "--since-minutes",
        type=int,
        help="override the look-back window (lmp5 and rtd only)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.since_minutes is not None:
        if args.job not in ("lmp5", "lmp5_catchup", "rtd"):
            parser.error("--since-minutes applies only to lmp5, lmp5_catchup and rtd")
        runner = ingest.ingest_rtd if args.job == "rtd" else ingest.ingest_lmp5
        result = runner(client(), since_minutes=args.since_minutes)
        outcome = {
            "job": args.job,
            "status": result.status,
            "rows_seen": result.rows_seen,
            "rows_inserted": result.rows_inserted,
            "rows_revised": result.rows_revised,
        }
    else:
        outcome = run_job(args.job)

    print(json.dumps(outcome, indent=2, default=str))
    db.close_pool()

    if outcome.get("status") == "error":
        return 1
    if outcome.get("status") == "empty":
        print(
            "\nZero rows. The request succeeded, so this is usually a wrong query "
            "parameter name rather than an outage — run:\n"
            f"  python scripts/describe_endpoint.py <endpoint>",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
