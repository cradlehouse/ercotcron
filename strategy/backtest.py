#!/usr/bin/env python3
"""Walk-forward backtest with an explicit information set.

    python strategy/backtest.py --points HB_NORTH,HB_HOUSTON --days 180

The information set is built from delivery timestamps, not from the bitemporal
`*_asof()` functions. Those functions are correct but vacuous on this database:
every backfilled row carries the backfill time in both `price_from` and
`ingested_at`, so a historical as-of returns nothing and a current one returns
everything. Only rows collected live since roughly 26 Jul 2026 carry real
as-of information. See strategy/db.py.

What that costs: this harness is exact about look-ahead on the primary series
(a decision at DAM close cannot see a real-time price that had not settled),
and blind to ERCOT's later revisions of already-published prices. The database
holds ~117k such revisions, so treat results as slightly optimistic on any
strategy whose edge lives in thinly-traded intervals, where revisions cluster.

The baseline strategy is deliberately dumb: fade the day-ahead premium when it
is unusually wide versus its own trailing distribution. It exists to give the
harness something to score. Replace `generate_signals`; keep the harness.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402

# Day-ahead market closes at 10:00 CPT for the next operating day. A decision
# made after this is not a decision, it is hindsight.
DAM_CLOSE_HOUR_CPT = 10


@dataclass
class Fold:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def walk_forward(start: datetime, end: datetime, folds: int, embargo_days: int = 2):
    """Expanding window with an embargo gap between train and test.

    The embargo matters because price series autocorrelate across days. Without
    a gap, the last training rows and the first test rows share the same weather
    and outage state, and the model scores itself on what it has already seen.
    """
    span = (end - start) / (folds + 1)
    for i in range(1, folds + 1):
        test_start = start + span * i
        yield Fold(
            train_start=start,
            train_end=test_start - timedelta(days=embargo_days),
            test_start=test_start,
            test_end=test_start + span,
        )


def as_of_for(target_interval: datetime) -> datetime:
    """The moment you would actually have had to decide: DAM close on the day
    before the operating day. CPT is UTC-5 in daylight time."""
    day_before = (target_interval - timedelta(days=1)).date()
    return datetime.combine(
        day_before, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(hours=DAM_CLOSE_HOUR_CPT + 5)


def generate_signals(history: list[dict], target_intervals: list[datetime],
                     threshold: float = 1.5) -> list[dict]:
    """Baseline: short the DA/RT spread when it is more than `threshold`
    standard deviations above its trailing mean for that settlement point.

    `history` must span the test window as well as the training window: at each
    target's DAM close the trader knows every spread that had already settled,
    including ones from earlier in the same test period. Passing only the
    training rows makes the trailing window frozen, so one z per point decides
    the whole fold — one bet reported as hundreds, with a hit rate to match.
    """
    if not history:
        return []

    by_point: dict[str, list[tuple[datetime, float]]] = {}
    for row in history:
        ts = datetime.fromisoformat(row["interval_start"])
        by_point.setdefault(row["settlement_point"], []).append((ts, float(row["spread"])))
    for series in by_point.values():
        series.sort()

    targets = sorted(target_intervals)
    signals = []
    for point, series in by_point.items():
        # Cutoffs advance monotonically with the sorted targets, so one pointer
        # and running sums replace an O(targets x history) rescan per target.
        idx = 0
        n = 0
        total = 0.0
        total_sq = 0.0
        last = None
        for target in targets:
            cutoff = as_of_for(target)
            while idx < len(series) and series[idx][0] < cutoff:
                value = series[idx][1]
                n += 1
                total += value
                total_sq += value * value
                last = value
                idx += 1
            if n < 30 or last is None:
                continue
            mean = total / n
            var = total_sq / n - mean * mean
            if var <= 0:
                continue
            z = (last - mean) / (var ** 0.5)
            if abs(z) < threshold:
                continue
            signals.append({
                "settlement_point": point,
                "target_interval": target,
                "direction": -1 if z > 0 else 1,
                "predicted_spread": mean,
                "confidence": min(abs(z) / 4, 1.0),
            })
    return signals


def score(signals: list[dict], realised: dict[tuple[str, datetime], float],
          mw: float = 1.0, fee_per_mwh: float = 0.10) -> dict:
    """Score signals against what actually happened. Unmatched signals are
    dropped and counted — a strategy that only fires when data exists is
    already cheating."""
    pnl, wins, matched, missing = 0.0, 0, 0, 0
    for s in signals:
        key = (s["settlement_point"], s["target_interval"])
        if key not in realised:
            missing += 1
            continue
        matched += 1
        gross = s["direction"] * realised[key] * mw
        net = gross - fee_per_mwh * mw
        pnl += net
        wins += net > 0
    return {
        "orders": matched,
        "unmatched": missing,
        "net_pnl": round(pnl, 2),
        "hit_rate": round(wins / matched, 3) if matched else None,
        "avg_pnl": round(pnl / matched, 4) if matched else None,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--points", default="", help="Comma separated; blank = tracked")
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--folds", type=int, default=12)
    p.add_argument("--threshold", type=float, default=1.5)
    p.add_argument("--end", default="", help="ISO date; blank = now")
    args = p.parse_args()

    points = [s.strip() for s in args.points.split(",") if s.strip()] or db.tracked_points()
    end = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
           if args.end else datetime.now(timezone.utc))
    start = end - timedelta(days=args.days)

    print(f"{len(points)} points, {args.days} days, {args.folds} folds")
    print(f"window {start:%Y-%m-%d} .. {end:%Y-%m-%d}\n")
    print(f"{'fold':>4} {'test window':<26} {'orders':>7} {'unmatched':>10} {'hit':>6} {'net pnl':>10}")

    totals = {"orders": 0, "net_pnl": 0.0, "unmatched": 0}
    hits = []
    for i, fold in enumerate(walk_forward(start, end, args.folds), 1):
        train = db.spread(points, fold.train_start.isoformat(), fold.train_end.isoformat())
        test = db.spread(points, fold.test_start.isoformat(), fold.test_end.isoformat())
        # The trader's knowledge grows through the test window; `generate_signals`
        # cuts this off per target at that target's DAM close, so passing the
        # test rows here leaks nothing.
        history = train + test

        realised = {
            (r["settlement_point"], datetime.fromisoformat(r["interval_start"])):
                float(r["spread"]) for r in test
        }
        targets = sorted({k[1] for k in realised})
        signals = generate_signals(history, targets, args.threshold)
        result = score(signals, realised)

        totals["orders"] += result["orders"]
        totals["net_pnl"] += result["net_pnl"]
        totals["unmatched"] += result["unmatched"]
        if result["hit_rate"] is not None:
            hits.append(result["hit_rate"])
        window = f"{fold.test_start:%Y-%m-%d}..{fold.test_end:%Y-%m-%d}"
        print(f"{i:>4} {window:<26} {result['orders']:>7} {result['unmatched']:>10} "
              f"{str(result['hit_rate'] or '-'):>6} {result['net_pnl']:>10,.2f}")

    print(f"\ntotal: {totals['orders']:,} orders, {totals['unmatched']:,} unmatched, "
          f"${totals['net_pnl']:,.2f} net (1 MW, $0.10/MWh fees)")
    if hits:
        print(f"hit rate across folds: mean {statistics.fmean(hits):.3f}  "
              f"min {min(hits):.3f}  max {max(hits):.3f}  "
              f"folds positive {sum(1 for h in hits if h > 0.5)}/{len(hits)}")
    print("\nBefore believing any of this: how many strategy variants did you")
    print("try to get here? Divide your confidence accordingly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
