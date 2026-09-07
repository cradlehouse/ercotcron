"""The one TOU calendar — the holiday rules the scorers used to disagree on."""
import datetime as dt

from ercot.calendar import nerc_holidays, tou_hours, tou_of


class TestHolidays:
    def test_labor_day_2026(self):
        assert dt.date(2026, 9, 7) in nerc_holidays(2026)
        assert tou_of(dt.date(2026, 9, 7), 12) == "PeakWE"

    def test_saturday_holiday_not_substituted(self):
        # Jul 4 2026 is a Saturday: NERC does NOT observe it on Friday.
        assert dt.date(2026, 7, 3) not in nerc_holidays(2026)
        assert tou_of(dt.date(2026, 7, 3), 12) == "PeakWD"

    def test_sunday_holiday_observed_monday(self):
        # Jul 4 2027 is a Sunday: observed Monday Jul 5.
        assert dt.date(2027, 7, 5) in nerc_holidays(2027)
        assert tou_of(dt.date(2027, 7, 5), 12) == "PeakWE"

    def test_floating_holidays_2026(self):
        h = nerc_holidays(2026)
        assert dt.date(2026, 5, 25) in h    # Memorial: last Monday of May
        assert dt.date(2026, 11, 26) in h   # Thanksgiving: 4th Thursday

    def test_six_holidays_every_year(self):
        for y in range(2024, 2031):
            assert len(nerc_holidays(y)) == 6, y


class TestTou:
    def test_off_peak_edges(self):
        d = dt.date(2026, 9, 8)  # a plain Tuesday
        assert tou_of(d, 6) == "Off-peak"
        assert tou_of(d, 7) == "PeakWD"
        assert tou_of(d, 22) == "PeakWD"
        assert tou_of(d, 23) == "Off-peak"

    def test_weekend(self):
        assert tou_of(dt.date(2026, 9, 5), 12) == "PeakWE"  # Saturday

    def test_month_hours_match_the_auction(self):
        # OCT 2026 block sizes as published: no holiday, 22 weekdays.
        assert tou_hours(2026, 10) == {"PeakWD": 352, "PeakWE": 144, "Off-peak": 248}
        # SEP 2026: Labor Day moves 16 hours from PeakWD to PeakWE.
        assert tou_hours(2026, 9) == {"PeakWD": 336, "PeakWE": 144, "Off-peak": 240}
