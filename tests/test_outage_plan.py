"""Planned outage capacity editions: stored whole, or not at all."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from ercot import outage_plan

POSTED = datetime(2026, 10, 14, 18, 0, 8)
HEAD = "OperatingDate,ResourcePOLnonIRRnonPUN,ResourcePOLESR\n"


def test_one_row_per_column_with_a_daily_series():
    text = HEAD + "10/21/2026,14892,872\n10/22/2026,15035,\n10/23/2026,15169,870\n"
    rows = outage_plan.edition_rows(POSTED, text)
    assert [r[3] for r in rows] == ["ResourcePOLnonIRRnonPUN", "ResourcePOLESR"]
    product, posted, first, _col, vals = rows[1]
    assert (product, posted, first) == ("NP3-161-CD", POSTED, date(2026, 10, 21))
    assert vals == [872.0, None, 870.0]          # a blank stays missing, not 0


def test_a_gap_in_the_dates_rejects_the_edition():
    text = HEAD + "10/21/2026,1,1\n10/23/2026,2,2\n"
    with pytest.raises(ValueError):
        outage_plan.edition_rows(POSTED, text)
