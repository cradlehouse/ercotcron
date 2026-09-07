"""The one TOU calendar. Every scorer, scanner and exhibit imports this.

ERCOT CRR time-of-use blocks follow the NERC holiday convention:

  PeakWD   HE 7-22, Monday-Friday, excluding NERC holidays
  PeakWE   HE 7-22, Saturday/Sunday and NERC holidays
  Off-peak HE 1-6 and 23-24, every day

The six NERC holidays are New Year's Day, Memorial Day, Independence Day,
Labor Day, Thanksgiving and Christmas. A holiday falling on a SUNDAY is
observed the following Monday; one falling on a SATURDAY is NOT substituted
(the day is already off-peak weekend). This is NERC's rule, not the federal
observed-holiday rule — the old per-file copies disagreed exactly here
(some shifted Sat->Fri, most had no holidays at all), which is why Labor Day
scored as PeakWD in one scorer and PeakWE in another.

The SQL twin of this function is ercot_tou(date, int) in
supabase/migrations/20260907060000_tou_sql.sql. Change both together.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    off = (weekday - d.weekday()) % 7
    return d + dt.timedelta(days=off + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    if month == 12:
        d = dt.date(year, 12, 31)
    else:
        d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


@lru_cache(maxsize=None)
def nerc_holidays(year: int) -> frozenset[dt.date]:
    """Observed NERC holidays for a year (Sunday -> following Monday)."""
    fixed = [dt.date(year, 1, 1), dt.date(year, 7, 4), dt.date(year, 12, 25)]
    floating = [
        _last_weekday(year, 5, 0),      # Memorial Day: last Monday of May
        _nth_weekday(year, 9, 0, 1),    # Labor Day: first Monday of September
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving: fourth Thursday of November
    ]
    out = set(floating)
    for d in fixed:
        out.add(d + dt.timedelta(days=1) if d.weekday() == 6 else d)
    return frozenset(out)


def is_nerc_holiday(d: dt.date) -> bool:
    return d in nerc_holidays(d.year)


def tou_of(d: dt.date, he: int) -> str:
    """TOU block for a delivery date and hour-ending (1-24)."""
    if not (7 <= he <= 22):
        return "Off-peak"
    return "PeakWE" if d.weekday() >= 5 or is_nerc_holiday(d) else "PeakWD"


def tou_hours(year: int, month: int) -> dict[str, int]:
    """Exact TOU hour counts for a delivery month (holiday-aware).

    Ignores DST (CRR TOU blocks are defined on hour-endings 1-24 per day),
    matching how the auction defines block sizes.
    """
    import calendar as _cal
    out = {"PeakWD": 0, "PeakWE": 0, "Off-peak": 0}
    for day in range(1, _cal.monthrange(year, month)[1] + 1):
        for he in range(1, 25):
            out[tou_of(dt.date(year, month, day), he)] += 1
    return out
