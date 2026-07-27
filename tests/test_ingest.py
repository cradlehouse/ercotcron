"""Report rows to database rows.

These tests feed ERCOT-shaped payloads through the real parsers with the
database stubbed out, so a casing change or a filter regression shows up here
rather than as a null column in production.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx
import pytest

from ercot import db, ingest
from ercot.client import ErcotClient


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ERCOT_SUBSCRIPTION_KEY", "test-key")
    monkeypatch.setenv("TRACKED_POINTS", "HB_NORTH,HB_HOUSTON")


@pytest.fixture
def captured(monkeypatch):
    """Capture what ingest would have written."""
    calls = {}

    def fake_upsert(table, columns, rows, *, conflict, update):
        calls["table"] = table
        calls["columns"] = list(columns)
        calls["rows"] = list(rows)
        return (len(list(rows)), 0)

    def fake_insert(table, columns, rows, *, conflict):
        calls["table"] = table
        calls["columns"] = list(columns)
        calls["rows"] = list(rows)
        return len(calls["rows"])

    monkeypatch.setattr(db, "upsert_rows", fake_upsert)
    monkeypatch.setattr(db, "insert_rows_ignore_dupes", fake_insert)
    return calls


def client_returning(fields, data) -> ErcotClient:
    payload = {
        "fields": [{"name": f} for f in fields],
        "data": data,
        "_meta": {"totalPages": 1},
    }
    client = ErcotClient()
    client._http = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    )
    client._token = "test-token"
    client._token_expires_at = float("inf")
    return client


def as_dict(calls) -> dict:
    return dict(zip(calls["columns"], calls["rows"][0]))


class TestTrackedPoints:
    def test_defaults_to_hubs_and_zones(self, monkeypatch):
        monkeypatch.delenv("TRACKED_POINTS", raising=False)
        points = ingest.tracked_points()
        assert "HB_HUBAVG" in points and "LZ_HOUSTON" in points

    def test_star_keeps_everything(self, monkeypatch):
        monkeypatch.setenv("TRACKED_POINTS", "*")
        assert ingest.tracked_points() is None

    def test_explicit_list_is_upper_cased(self, monkeypatch):
        monkeypatch.setenv("TRACKED_POINTS", "hb_north, hb_south")
        assert ingest.tracked_points() == {"HB_NORTH", "HB_SOUTH"}


class TestDam:
    def test_maps_a_row(self, captured):
        client = client_returning(
            ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice", "DSTFlag"],
            [["2026-07-15", "1", "HB_NORTH", 31.25, "N"]],
        )
        result = ingest.ingest_dam(client)

        assert result.rows_seen == 1
        row = as_dict(captured)
        assert captured["table"] == "dam_spp"
        assert row["settlement_point"] == "HB_NORTH"
        assert row["price"] == 31.25
        assert row["hour_ending"] == 1
        assert row["delivery_date"] == date(2026, 7, 15)
        assert row["interval_start"] == datetime(2026, 7, 15, 5, tzinfo=timezone.utc)

    def test_filters_untracked_points(self, captured):
        client = client_returning(
            ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice"],
            [["2026-07-15", "1", "HB_NORTH", 31.25],
             ["2026-07-15", "1", "LZ_WEST", 28.0]],
        )
        assert ingest.ingest_dam(client).rows_seen == 1
        assert as_dict(captured)["settlement_point"] == "HB_NORTH"

    def test_tolerates_drifted_casing(self, captured):
        # Same report, ERCOT's other spelling of every column.
        client = client_returning(
            ["DeliveryDate", "HourEnding", "SettlementPointName", "SPP", "dstFlag"],
            [["2026-07-15", "01:00", "HB_NORTH", 31.25, "N"]],
        )
        assert ingest.ingest_dam(client).rows_seen == 1
        assert as_dict(captured)["price"] == 31.25

    def test_skips_rows_missing_a_price(self, captured):
        client = client_returning(
            ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice"],
            [["2026-07-15", "1", "HB_NORTH", None]],
        )
        assert ingest.ingest_dam(client).rows_seen == 0

    def test_repeated_hour_is_offset(self, captured):
        client = client_returning(
            ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice", "DSTFlag"],
            [["2026-11-01", "2", "HB_NORTH", 20.0, "Y"]],
        )
        ingest.ingest_dam(client)
        assert as_dict(captured)["interval_start"] == datetime(
            2026, 11, 1, 7, tzinfo=timezone.utc)


class TestRtm:
    def test_maps_interval(self, captured):
        client = client_returning(
            ["deliveryDate", "deliveryHour", "deliveryInterval", "settlementPoint",
             "settlementPointPrice"],
            [["2026-07-15", "1", "3", "HB_HOUSTON", 45.5]],
        )
        assert ingest.ingest_rtm(client).rows_seen == 1
        row = as_dict(captured)
        assert captured["table"] == "rt_spp"
        assert row["delivery_interval"] == 3
        assert row["interval_start"] == datetime(2026, 7, 15, 5, 30, tzinfo=timezone.utc)


class TestLmp5:
    def test_floors_to_the_five_minute_interval(self, captured):
        client = client_returning(
            ["SCEDTimestamp", "settlementPoint", "LMP", "energyComponent",
             "congestionComponent", "lossComponent", "repeatHourFlag"],
            [["2026-07-15 05:07:00", "HB_NORTH", 99.0, 30.0, 68.0, 1.0, "N"]],
        )
        assert ingest.ingest_lmp5(client).rows_seen == 1
        row = as_dict(captured)
        assert captured["table"] == "rt_lmp_5min"
        assert row["interval_start"] == datetime(2026, 7, 15, 10, 5, tzinfo=timezone.utc)
        assert row["sced_timestamp"] == datetime(2026, 7, 15, 10, 7, tzinfo=timezone.utc)
        assert row["congestion"] == 68.0


class TestRtd:
    def test_target_interval_is_derived_from_interval_ending(self, captured):
        client = client_returning(
            ["RTDTimestamp", "intervalEnding", "settlementPoint", "LMP"],
            [["2026-07-15 05:00:00", "2026-07-15 05:20:00", "HB_NORTH", 55.0]],
        )
        assert ingest.ingest_rtd(client).rows_seen == 1
        row = as_dict(captured)
        assert captured["table"] == "rtd_lmp"
        assert row["rtd_timestamp"] == datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
        # intervalEnding 05:20 names the interval starting 05:15.
        assert row["interval_start"] == datetime(2026, 7, 15, 10, 15, tzinfo=timezone.utc)


class TestResultStatus:
    def test_zero_rows_reports_empty_not_ok(self):
        # 'empty' is the signature of a wrong query parameter name, which ERCOT
        # does not report as an error.
        assert ingest.Result(rows_seen=0).status == "empty"
        assert ingest.Result(rows_seen=1).status == "ok"


class TestHourEnding:
    @pytest.mark.parametrize("value,expected", [
        (1, 1), ("1", 1), ("01", 1), ("01:00", 1), ("0100", 1), ("24", 24), ("24:00", 24),
    ])
    def test_spellings(self, value, expected):
        assert ingest._hour_ending(value) == expected


class TestExcludedPointType:
    """Load zones publish LZ and LZEW under one name; only one may be stored."""

    def test_lzew_is_excluded(self):
        from ercot.ingest import excluded_type

        assert excluded_type({"settlementPointType": "LZEW"}) is True
        assert excluded_type({"settlementPointType": "lzew"}) is True

    def test_settlement_types_are_kept(self):
        from ercot.ingest import excluded_type

        for kind in ("LZ", "HU", "AH", "SH", "RN"):
            assert excluded_type({"settlementPointType": kind}) is False

    def test_absent_type_is_kept(self):
        # dam and lmp5 publish no type field at all; those rows must survive.
        from ercot.ingest import excluded_type

        assert excluded_type({}) is False
        assert excluded_type({"settlementPointType": None}) is False


class TestCrrAuctionNames:
    """Monthly and long-term auctions name their report files differently."""

    def test_monthly(self):
        from ercot.crr import _auction_name

        assert _auction_name(
            "rpt.00011201.0.20260723.080107728.AUG2026MonthlyCRRAuctionResults.zip"
        ) == "AUG2026Monthly"

    def test_long_term(self):
        from ercot.crr import _auction_name

        assert _auction_name(
            "rpt.00011203.0.20260709.080132200.20272nd6AnnualAuctionSeq3CRRAuctionResults.zip"
        ) == "20272nd6AnnualAuctionSeq3"

    def test_unrecognised_falls_back_to_filename(self):
        # A notice, not a results file — must not be mistaken for an auction.
        from ercot.crr import _auction_name

        name = "rpt.00011200.0.20260702.100552512.AUG2026MonthlyCRRAuctionNotice.zip"
        assert _auction_name(name) == name

    def test_dates_parse_us_format(self):
        # The API returns ISO dates; these CSVs use MM/DD/YYYY.
        from ercot.crr import _date

        assert _date("08/01/2026") == "2026-08-01"
        assert _date("") is None
