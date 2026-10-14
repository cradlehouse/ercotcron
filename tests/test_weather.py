"""Weather forecast vintages: the archive must keep what was seen, as seen."""

from __future__ import annotations

from datetime import UTC, datetime

from ercot import db, weather

SEEN = datetime(2026, 10, 14, 12, 37, tzinfo=UTC)
INIT = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
META = {m: (INIT, INIT, "ref") for m in weather.MODELS}


def hourly(times, **series):
    return {"time": times, **{f"wind_speed_100m_{m}": v for m, v in series.items()}}


def test_drops_hours_before_the_fetch_and_keeps_nulls():
    h = hourly(["2026-10-14T11:00", "2026-10-14T12:00", "2026-10-14T13:00"],
               ecmwf_ifs025=[10.0, None, 12.5])
    [row] = weather.vintage_rows("West", 32.45, -100.4, h, SEEN, META)
    row = dict(zip(weather.VINTAGE_COLUMNS, row))
    assert row["valid_start"] == datetime(2026, 10, 14, 12, tzinfo=UTC)
    assert row["vals"] == [None, 12.5]            # missing stays missing, not 0
    assert row["first_seen_at"] == SEEN
    assert row["ref_run_init"] == INIT and row["run_meta_source"] == "ref"
    assert row["site_id"] == "West:32.45,-100.4"


def test_same_series_same_hash_changed_value_new_hash():
    times = ["2026-10-14T12:00", "2026-10-14T13:00"]
    a = weather.vintage_rows("West", 1, 2, hourly(times, ecmwf_ifs025=[1.0, 2.0]), SEEN, META)
    b = weather.vintage_rows("West", 1, 2, hourly(times, ecmwf_ifs025=[1.0, 2.0]), SEEN, META)
    c = weather.vintage_rows("West", 1, 2, hourly(times, ecmwf_ifs025=[1.0, 2.1]), SEEN, META)
    sha = weather.VINTAGE_COLUMNS.index("series_sha256")
    assert a[0][sha] == b[0][sha] != c[0][sha]


def test_gappy_grid_is_refused_not_misaligned():
    h = hourly(["2026-10-14T12:00", "2026-10-14T14:00"], ecmwf_ifs025=[1.0, 2.0])
    assert weather.vintage_rows("West", 1, 2, h, SEEN, META) == []


def test_all_null_or_absent_models_write_nothing():
    h = hourly(["2026-10-14T12:00"], ecmwf_ifs025=[None])
    assert weather.vintage_rows("West", 1, 2, h, SEEN, META) == []


def test_archive_failure_does_not_block_the_live_table(monkeypatch):
    times = ["2026-10-14T12:00", "2099-01-01T00:00"]
    monkeypatch.setattr(weather, "SITES", {"West": [(1.0, 2.0)]})
    monkeypatch.setattr(weather, "_run_meta", lambda m: (None, None, None))
    monkeypatch.setattr(weather, "_fetch_site",
                        lambda *a: hourly(times, ecmwf_ifs025=[5.0, 6.0]))
    upserted = {}

    def fake_upsert(table, columns, rows, *, conflict, update):
        upserted["rows"] = list(rows)
        return (len(upserted["rows"]), 0)

    def boom(*a, **k):
        raise RuntimeError("archive down")

    monkeypatch.setattr(db, "upsert_rows", fake_upsert)
    monkeypatch.setattr(db, "insert_rows_ignore_dupes", boom)
    res = weather.ingest_weather()
    assert res.rows_inserted == 2 and len(upserted["rows"]) == 2
