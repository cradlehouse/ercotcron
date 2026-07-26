"""Central-time to UTC conversion.

ERCOT reports a delivery date plus an hour ending (and often an interval) on a
Central clock, with a DST flag marking the repeated hour in the autumn
transition. Getting this wrong silently shifts an hour of prices, so every
conversion in the codebase goes through here.

Hour ending convention: HE 1 covers 00:00–01:00, so interval_start = date +
(hour_ending - 1) hours. HE 25 appears on the autumn long day and is the repeat.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .config import CENTRAL, UTC


class NonexistentLocalTime(ValueError):
    """A wall-clock time skipped by the spring-forward transition."""


def _localize(naive: datetime, *, repeated: bool) -> datetime:
    """Attach Central time to a naive wall-clock time.

    `repeated` selects the second pass through an ambiguous hour (the autumn
    fall-back). Python's `fold` attribute expresses exactly this.
    """
    return naive.replace(tzinfo=CENTRAL, fold=1 if repeated else 0)


def central_wall_to_utc(naive: datetime, *, repeated: bool = False) -> datetime:
    """Convert Central wall-clock to an absolute instant.

    Raises on a time the spring-forward transition skipped. Python maps such a
    time onto the same instant as the following hour, which would collide on the
    primary key and silently overwrite a real hour of prices. ERCOT omits the
    skipped hour from its reports, so seeing one means an assumption is wrong —
    which is worth an exception rather than a corrupted row.
    """
    localized = _localize(naive, repeated=repeated)
    instant = localized.astimezone(UTC)
    if instant.astimezone(CENTRAL).replace(tzinfo=None) != naive:
        raise NonexistentLocalTime(
            f"{naive.isoformat()} does not exist in America/Chicago "
            "(skipped by the spring-forward transition)"
        )
    return instant


def dam_interval_start(delivery_date: date, hour_ending: int, *, dst_flag: bool = False) -> datetime:
    """Day-ahead hourly interval start as an absolute instant."""
    if not 1 <= hour_ending <= 25:
        raise ValueError(f"hour_ending out of range: {hour_ending}")
    # HE 25 is the repeated 01:00–02:00 hour on the autumn long day.
    if hour_ending == 25:
        naive = datetime.combine(delivery_date, datetime.min.time()) + timedelta(hours=1)
        return central_wall_to_utc(naive, repeated=True)
    naive = datetime.combine(delivery_date, datetime.min.time()) + timedelta(hours=hour_ending - 1)
    return central_wall_to_utc(naive, repeated=dst_flag)


def rt_interval_start(
    delivery_date: date,
    delivery_hour: int,
    delivery_interval: int,
    *,
    dst_flag: bool = False,
) -> datetime:
    """Real-time 15-minute interval start as an absolute instant.

    delivery_hour is an hour ending (1–25); delivery_interval is 1–4 within it.
    """
    if not 1 <= delivery_interval <= 4:
        raise ValueError(f"delivery_interval out of range: {delivery_interval}")
    hour_start = dam_interval_start(delivery_date, delivery_hour, dst_flag=dst_flag)
    return hour_start + timedelta(minutes=15 * (delivery_interval - 1))


def parse_ercot_timestamp(value: str, *, repeated: bool = False) -> datetime:
    """Parse a Central wall-clock timestamp string from a report.

    Accepts the ISO-ish forms ERCOT uses across reports. A value that already
    carries an offset is respected as-is.
    """
    if value is None:
        raise ValueError("timestamp is None")
    text = str(value).strip().replace("T", " ")
    if text.endswith("Z"):
        return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)

    # An explicit offset means the instant is already unambiguous.
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unrecognised ERCOT timestamp: {value!r}") from None

    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    return central_wall_to_utc(parsed, repeated=repeated)


def floor_to_5min(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0, minute=(moment.minute // 5) * 5)


def central_date(moment: datetime) -> date:
    """The ERCOT operating day a UTC instant falls in."""
    return moment.astimezone(CENTRAL).date()


def is_repeat_hour(flag: object) -> bool:
    """ERCOT spells the repeated-hour flag as Y/N, true/false, or 1/0."""
    if isinstance(flag, bool):
        return flag
    if flag is None:
        return False
    return str(flag).strip().lower() in {"y", "yes", "true", "t", "1"}
