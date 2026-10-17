"""Daily DAM constraints, 60-day disclosure and NP3-560 vintages: parsed the
way the backfill loaders parse them, and stored whole or not at all."""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager
from datetime import date, datetime

import pytest

from ercot import dam_constraints, dam_disclosure, forecast_vintages, jobs

# ------------------------------------------------------------ constraints --

CONSTRAINT_CSV = (
    "DeliveryDate,HourEnding,ConstraintID,ConstraintName,ContingencyName,ConstraintLimit,"
    "ConstraintValue,ViolationAmount,ShadowPrice,FromStation,ToStation,FromStationkV,ToStationkV\n"
    "10/18/2026,07:00,12,PNHNDL,BASE CASE,1000,1000,0,14.5,AJ_SW, ,345,345\n"
    "10/18/2026,08:00,12,PNHNDL,,1000,990,,,AJ_SW,BRKS,345,\n"
    "bad,row,,,,,,,,,,,\n"
)


def test_constraint_rows_match_the_backfill_columns():
    rows = dam_constraints.file_rows(CONSTRAINT_CSV)
    assert len(rows) == 2                         # the malformed row is dropped
    assert rows[0] == (date(2026, 10, 18), 7, 12, "PNHNDL", "BASE CASE",
                       1000.0, 1000.0, 0.0, 14.5, "AJ_SW", None, 345.0, 345.0)
    assert rows[1][4] == ""                        # missing contingency -> '' (part of the key)
    assert rows[1][8] is None and rows[1][12] is None   # blanks stay missing, not 0


# ------------------------------------------------------------- disclosure --

GEN_HDR = "Delivery Date,Hour Ending,Repeated Hour Flag DST,Resource Name,Resource Type,Settlement Point Name,Awarded Quantity,HSL,Resource Status\n"
VIRT_HDR = "Delivery Date,Hour Ending,Repeated Hour Flag DST,Settlement Point,Energy Only Offer Award in MW\n"
PTP_HDR = "Delivery Date,Hour Ending,Repeated Hour Flag DST,Source,Sink,Award ID,MW\n"


def disclosure_zip(n_resources: int = 600, hours: int = 24, mw: float = 20.0) -> zipfile.ZipFile:
    gen = [GEN_HDR]
    for k in range(n_resources):
        for he in range(1, hours + 1):
            gen.append(f"08/18/2026,{he:02d}:00,N,UNIT{k},WIND,SP{k},{mw},{mw * 2},ON\n")
    virt = [VIRT_HDR] + [f"08/18/2026,{he:02d}:00,N,HB_NORTH,5\n" for he in range(1, hours + 1)]
    virt.append("08/18/2026,01:00,N,HB_NORTH,2.5\n")   # a second offer, same slot, sums
    ptp = [PTP_HDR] + [f"08/18/2026,{he:02d}:00,N,A,B,99,{he}\n" for he in range(1, hours + 1)]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("60d_DAM_Gen_Resource_Data-18-AUG-26.csv", "".join(gen))
        z.writestr("60d_DAM_EnergyOnlyOfferAwards-18-AUG-26.csv", "".join(virt))
        z.writestr("60d_DAM_PTP_Obligation_OptionAwards-18-AUG-26.csv", "".join(ptp))
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_a_disclosure_day_becomes_hourly_arrays_in_three_tables():
    parsed = dam_disclosure.parse(disclosure_zip())
    rec = parsed[date(2026, 8, 18)]
    assert dam_disclosure.validate(rec) is None
    tables = dam_disclosure.day_rows(date(2026, 8, 18), rec, "2026-10-17T00:45:06")
    res = tables["dam_resource_awards"]
    assert len(res) == 600
    assert res[0][:4] == (date(2026, 8, 18), "UNIT0", "WIND", "SP0")
    assert res[0][4] == [20.0] * 24 and res[0][6] == ["ON"] * 24
    (virt,) = tables["dam_virtual_awards"]
    assert virt[2][0] == 7.5 and virt[3] == [0.0] * 24    # offers summed; no bids -> zeros
    (ptp,) = tables["dam_ptp_awards"]
    assert ptp[1:3] == ("A", "B") and ptp[3] == [float(h) for h in range(1, 25)]  # MW, not Award ID


@pytest.mark.parametrize(("kwargs", "why"), [
    ({"n_resources": 100}, "resources"),
    ({"hours": 20}, "hourly slots"),
    ({"mw": 1.0}, "implausible"),
])
def test_a_broken_disclosure_day_is_rejected(kwargs, why):
    rec = dam_disclosure.parse(disclosure_zip(**kwargs))[date(2026, 8, 18)]
    assert why in dam_disclosure.validate(rec)


class FakeConn:
    def __init__(self, stored):
        self.stored, self.copied = stored, []

    def execute(self, *_a):
        return self

    def fetchall(self):
        return self.stored

    def cursor(self):
        return self

    def copy(self, sql):
        conn = self

        class Copy:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def write_row(self, row):
                conn.copied.append((sql.split()[1], row))
        return Copy()

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeClient:
    def __init__(self, archives, blob=b""):
        self.archives, self.blob, self.downloads = archives, blob, 0

    def get(self, _endpoint, _params):
        return {"archives": self.archives}

    def download(self, _url):
        self.downloads += 1
        return self.blob


def _patch_db(monkeypatch, conn):
    @contextmanager
    def connection():
        yield conn
    monkeypatch.setattr(dam_disclosure.db, "connection", connection)


def _zip_bytes(z: zipfile.ZipFile) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            out.writestr(n, z.read(n))
    return buf.getvalue()


POSTING = {"postDatetime": "2026-10-17T00:45:06", "_links": {"endpoint": {"href": "x"}}}


def test_a_posting_already_saved_is_not_downloaded_again(monkeypatch):
    conn = FakeConn([(date(2026, 8, 18), datetime(2026, 10, 17, 0, 45, 6))])
    _patch_db(monkeypatch, conn)
    client = FakeClient([POSTING])
    result = dam_disclosure.ingest_dam_disclosure(client)
    assert client.downloads == 0 and result.rows_inserted == 0


def test_a_new_posting_writes_all_three_tables(monkeypatch):
    conn = FakeConn([])
    _patch_db(monkeypatch, conn)
    client = FakeClient([POSTING], _zip_bytes(disclosure_zip()))
    result = dam_disclosure.ingest_dam_disclosure(client)
    assert result.rows_inserted == 602 and result.status == "ok"
    assert {t for t, _ in conn.copied} == {"dam_resource_awards", "dam_virtual_awards", "dam_ptp_awards"}


def test_a_posting_that_fails_validation_fails_the_run(monkeypatch):
    conn = FakeConn([])
    _patch_db(monkeypatch, conn)
    client = FakeClient([POSTING], _zip_bytes(disclosure_zip(n_resources=10)))
    with pytest.raises(ValueError):
        dam_disclosure.ingest_dam_disclosure(client)
    assert conn.copied == []


# ---------------------------------------------------------------- NP3-560 --

POSTED = datetime(2026, 10, 17, 9, 30)


def _forecast_csv(days: int, hours: int = 24) -> str:
    lines = ["DeliveryDate,HourEnding,North,South,DSTFlag"]
    for d in range(days):
        for he in range(1, hours + 1):
            lines.append(f"10/{17 + d}/2026,{he:02d}:00,{1000 + he},{'' if he == 3 else 500},N")
    return "\n".join(lines) + "\n"


def test_one_row_per_delivery_day_and_column():
    rows = forecast_vintages.edition_rows("NP3-560-CD", POSTED, _forecast_csv(7))
    assert len(rows) == 14
    north = next(r for r in rows if r[2] == date(2026, 10, 17) and r[3] == "North")
    assert north[:2] == ("NP3-560-CD", POSTED) and north[4][:2] == [1001.0, 1002.0]
    south = next(r for r in rows if r[2] == date(2026, 10, 17) and r[3] == "South")
    assert south[4][2] is None                   # a blank stays missing, not 0


def test_a_short_edition_is_rejected():
    with pytest.raises(ValueError):
        forecast_vintages.edition_rows("NP3-560-CD", POSTED, _forecast_csv(6))


def test_the_0930_edition_wins_else_the_latest():
    a = [{"postDatetime": t} for t in ("2026-10-17T08:30:00", "2026-10-17T09:30:00", "2026-10-17T09:45:00")]
    assert forecast_vintages.pick_edition(a)["postDatetime"].endswith("09:30:00")
    assert forecast_vintages.pick_edition(a[::2])["postDatetime"].endswith("09:45:00")
    assert forecast_vintages.pick_edition([]) is None


# ------------------------------------------------------------------- jobs --

def test_the_three_feeds_are_scheduled_away_from_the_crr_jobs():
    for name in ("dam_constraints", "dam_disclosure", "load_fcast_560"):
        job = jobs.JOBS[name]
        assert job.name == name and job.timezone == "America/Chicago"
        assert (job.trigger.get("hour"), job.trigger.get("minute")) not in {("8", "40"), ("8", "50")}
