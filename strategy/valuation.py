"""One valuation rule for every scan — the typical month, never the mean.

Both screens (market_scan: the whole traded universe; discover_paths: the
winners' paths) price a path from its per-month payouts. They used to do it
differently, and the difference is where October's worst rows came from:

  SPIKE CAP (Oct 2026, HKSN_SLR_ALL->ANCHOR_ALL)
    Discovery priced off the 12-month MEAN. A lottery path whose median month
    pays 6c but whose January paid 94c "was worth" 25c, the limit landed at
    16c, and only 2 of 10 fitted months ever paid that much. The old
    spike flag (mean > 3x hourly median) could not fire on an option: an
    OPT's hourly median is 0 on most paths. Now the value can never exceed
    the MEDIAN MONTH, so a limit of value/1.5 is beaten in at least half the
    months by construction — `beat_rate` reports it so the sheet can say so.

  FADE DETECTOR (Oct 2026, NBOHR_RN, SHAMROCK_RN)
    The detector compared the last three FITTED months to the typical month.
    NBOHR->RRANCHES paid $10-27 every month to June, then $0.22, $0.19, $0.48
    — but the collapse was in the held-out months (house rule: the trailing
    two months are never fitted), so the detector never saw it; and a 3-month
    mean would have diluted a single collapsed month anyway. Now the detector
    also reads `tail` — the settled months AFTER the fit window, through the
    latest complete month — and fires when the two most recent settled months
    both paid under a quarter of the median month. The tail can only REMOVE a
    path, never price one: the holdout stays out of the fit.

In-sample check (SEP-reconstructed, scored): the collapse trigger would have
dropped 17 rows, 4 of which filled and lost $468. Out-of-sample test
pre-registered 2 Oct 2026 against the October settlement (docs/preregistrations).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

MIN_MONTHS = 6          # fewer fitted months than this and there is no "typical"
FADE_RECENT = 0.30      # last 3 fitted months average under this x typical -> fading
COLLAPSE = 0.25         # two latest settled months each under this x median month
MARGIN = 1.5            # the published limit rule: value / 1.5


@dataclass
class MonthValue:
    typical: float              # the price base: min(median month, recent, target-month history)
    median_month: float         # the spike cap — value never exceeds this
    mean_month: float
    fading: bool
    reasons: list[str] = field(default_factory=list)
    beat_rate: float | None = None   # share of fitted months paying >= value / MARGIN
    months: int = 0


def value_months(fit: list[float], tail: list[float] | None = None,
                 target: list[float] | None = None) -> MonthValue | None:
    """Value a path from chronological per-month mean payouts.

    fit     months inside the fitting window, oldest first
    tail    settled months after the window (held out of the fit), oldest
            first — fade evidence only
    target  past payouts of the delivery month being bid (e.g. Nov 2024,
            Nov 2025) — a seasonal cap where history exists
    """
    if len(fit) < MIN_MONTHS:
        return None
    med = float(statistics.median(fit))
    mean = float(statistics.fmean(fit))
    reasons: list[str] = []

    recent = float(statistics.fmean(fit[-3:]))
    fading = recent < FADE_RECENT * med
    if fading:
        reasons.append("congestion fading — recent months far below the average")

    latest = (list(fit) + list(tail or []))[-2:]
    if med > 0 and len(latest) == 2 and all(x < COLLAPSE * med for x in latest):
        fading = True
        reasons.append(f"payout collapse — last two settled months paid "
                       f"${latest[0]:.2f} and ${latest[1]:.2f} vs a typical ${med:.2f}")

    typical = min(med, max(recent, 0.0))
    if target:
        typical = min(typical, max(float(statistics.fmean(target)), 0.0))

    if med > 0 and mean > 2 * med:
        reasons.append("spike-driven — the average month is more than twice the typical one")

    limit = typical / MARGIN
    beat = sum(1 for x in fit if x >= limit) / len(fit) if limit > 0 else None
    return MonthValue(typical=typical, median_month=med, mean_month=mean,
                      fading=fading, reasons=reasons, beat_rate=beat,
                      months=len(fit))
