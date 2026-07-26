"""Central-to-UTC conversion.

A DST error here shifts an hour of prices without raising anything, so the
transition days are tested explicitly. In 2026 US DST starts 8 March and ends
1 November.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ercot.timeutil import (
    NonexistentLocalTime,
    central_date,
    dam_interval_start,
    floor_to_5min,
    is_repeat_hour,
    parse_ercot_timestamp,
    rt_interval_start,
)

HOUR = timedelta(hours=1)


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


class TestDamIntervalStart:
    def test_hour_ending_one_is_midnight(self):
        # HE 1 covers 00:00-01:00 Central. In summer, CDT = UTC-5.
        assert dam_interval_start(date(2026, 7, 15), 1) == utc(2026, 7, 15, 5)

    def test_hour_ending_24_is_last_hour_of_day(self):
        # HE 24 covers 23:00-00:00 Central, so it starts at 23:00 local.
        assert dam_interval_start(date(2026, 7, 15), 24) == utc(2026, 7, 16, 4)

    def test_winter_offset_is_six_hours(self):
        # CST = UTC-6.
        assert dam_interval_start(date(2026, 1, 15), 1) == utc(2026, 1, 15, 6)

    def test_spring_forward_rejects_the_skipped_hour(self):
        # 8 Mar 2026: 02:00 CST jumps to 03:00 CDT, so HE 3 (starting 02:00)
        # does not exist. Python would map it onto HE 4's instant, colliding on
        # the primary key and overwriting a real hour of prices. ERCOT omits the
        # hour, so encountering it must raise rather than corrupt a row.
        with pytest.raises(NonexistentLocalTime):
            dam_interval_start(date(2026, 3, 8), 3)

    def test_spring_forward_day_is_otherwise_continuous(self):
        # The 23-hour day runs 1, 2, then 4..24 with no repeated instants.
        hours = [dam_interval_start(date(2026, 3, 8), he) for he in (1, 2, 4, 5)]
        assert hours == sorted(hours)
        assert len(set(hours)) == 4
        assert all(b - a == HOUR for a, b in zip(hours, hours[1:]))

    def test_fall_back_repeated_hour_is_distinct(self):
        # 1 Nov 2026: 02:00 CDT falls back to 01:00 CST, so 01:00-02:00 happens
        # twice. The DST flag must separate the two passes by exactly an hour.
        first = dam_interval_start(date(2026, 11, 1), 2, dst_flag=False)
        second = dam_interval_start(date(2026, 11, 1), 2, dst_flag=True)
        assert second - first == HOUR
        assert first == utc(2026, 11, 1, 6)
        assert second == utc(2026, 11, 1, 7)

    def test_hour_ending_25_is_the_repeat(self):
        assert dam_interval_start(date(2026, 11, 1), 25) == utc(2026, 11, 1, 7)

    def test_rejects_out_of_range_hour(self):
        with pytest.raises(ValueError):
            dam_interval_start(date(2026, 7, 15), 0)
        with pytest.raises(ValueError):
            dam_interval_start(date(2026, 7, 15), 26)


class TestRtIntervalStart:
    def test_intervals_are_fifteen_minutes_apart(self):
        assert rt_interval_start(date(2026, 7, 15), 1, 1) == utc(2026, 7, 15, 5, 0)
        assert rt_interval_start(date(2026, 7, 15), 1, 2) == utc(2026, 7, 15, 5, 15)
        assert rt_interval_start(date(2026, 7, 15), 1, 4) == utc(2026, 7, 15, 5, 45)

    def test_interval_rolls_into_next_hour(self):
        assert rt_interval_start(date(2026, 7, 15), 2, 1) == utc(2026, 7, 15, 6, 0)

    def test_rejects_out_of_range_interval(self):
        with pytest.raises(ValueError):
            rt_interval_start(date(2026, 7, 15), 1, 5)


class TestParseTimestamp:
    @pytest.mark.parametrize("text", [
        "2026-07-15 05:30:00",
        "2026-07-15T05:30:00",
        "07/15/2026 05:30:00",
    ])
    def test_central_wall_clock_forms(self, text):
        assert parse_ercot_timestamp(text) == utc(2026, 7, 15, 10, 30)

    def test_explicit_utc_is_respected(self):
        assert parse_ercot_timestamp("2026-07-15T10:30:00Z") == utc(2026, 7, 15, 10, 30)

    def test_explicit_offset_is_respected(self):
        assert parse_ercot_timestamp("2026-07-15T05:30:00-05:00") == utc(2026, 7, 15, 10, 30)

    def test_repeated_hour_flag_selects_second_pass(self):
        first = parse_ercot_timestamp("2026-11-01 01:30:00", repeated=False)
        second = parse_ercot_timestamp("2026-11-01 01:30:00", repeated=True)
        assert second - first == HOUR

    def test_unrecognised_form_raises(self):
        with pytest.raises(ValueError):
            parse_ercot_timestamp("not a timestamp")


class TestHelpers:
    @pytest.mark.parametrize("flag,expected", [
        ("Y", True), ("y", True), ("yes", True), ("true", True), ("1", True), (True, True),
        ("N", False), ("no", False), ("false", False), ("0", False), ("", False),
        (None, False), (False, False),
    ])
    def test_repeat_hour_flag_spellings(self, flag, expected):
        assert is_repeat_hour(flag) is expected

    def test_floor_to_5min(self):
        assert floor_to_5min(utc(2026, 7, 15, 5, 7)) == utc(2026, 7, 15, 5, 5)
        assert floor_to_5min(utc(2026, 7, 15, 5, 5)) == utc(2026, 7, 15, 5, 5)

    def test_central_date_crosses_midnight_utc(self):
        # 03:00 UTC is still the previous evening in Texas.
        assert central_date(utc(2026, 7, 16, 3)) == date(2026, 7, 15)
