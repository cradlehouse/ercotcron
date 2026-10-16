from ercot import crr


def test_long_term_file_keeps_every_month_per_node():
    prices = [
        {"SourceSink": "HB_NORTH", "TimeOfUse": "PeakWD", "CalendarPeriod": "JAN_2025", "ShadowPricePerMWH": "1.5"},
        {"SourceSink": "HB_NORTH", "TimeOfUse": "PeakWD", "CalendarPeriod": "FEB_2025", "ShadowPricePerMWH": "2.5"},
        {"SourceSink": "", "TimeOfUse": "PeakWD", "CalendarPeriod": "FEB_2025", "ShadowPricePerMWH": "9"},
    ]
    rows = crr.point_price_rows("20251st6AnnualAuctionSeq1", prices)
    keys = {r[:4] for r in rows}
    assert len(rows) == 2 and len(keys) == 2
    assert {r[3] for r in rows} == {"JAN_2025", "FEB_2025"}


def test_key_includes_the_calendar_month():
    assert "calendar_period" in crr.POINT_PRICE_KEY
    assert "calendar_period" not in ["shadow_price"]
    assert crr.POINT_PRICE_KEY == crr.POINT_PRICE_COLUMNS[:4]
