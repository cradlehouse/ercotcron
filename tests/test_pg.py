"""Postgres-backed tests — the numbers we self-score in public, exercised
against the real schema.

Everything runs inside a transaction that ALWAYS rolls back, using the same
`set_config('request.jwt.claims', ...)` pattern PostgREST uses, so RPC
security is tested as the API actually evaluates it. Skipped wholesale when
DATABASE_URL is unset (offline CI still runs the pure-Python suite).

These exist because claim_holder shipped four security fixes with no test,
and the two September leaks (bid-sheet books, anon ref artifacts) were
exactly the kind of regression a rollback-transaction suite catches.
"""
from __future__ import annotations

import json
import os
import pathlib
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL unset — skipping Postgres-backed tests",
                allow_module_level=True)

import psycopg  # noqa: E402


@pytest.fixture
def cur():
    """A cursor inside a transaction that is rolled back no matter what."""
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as conn:
        conn.autocommit = False
        c = conn.cursor()
        yield c
        conn.rollback()


def as_user(cur, email: str | None = None, uid: str | None = None):
    """Impersonate an authenticated user the way PostgREST does."""
    if uid is None:
        cur.execute("select id::text from auth.users where email = %s", (email,))
        row = cur.fetchone()
        assert row, f"no such user: {email}"
        uid = row[0]
    cur.execute("select set_config('request.jwt.claims', %s, true)",
                (json.dumps({"sub": uid, "role": "authenticated"}),))
    return uid


STRANGER = str(uuid.uuid4())  # a uid that exists nowhere


class TestBidSheetBookGate:
    def test_member_without_claim_sees_only_public_books(self, cur):
        as_user(cur, uid=STRANGER)
        cur.execute("""select distinct jsonb_array_elements(get_bid_sheet()->'valuations')->>'book'""")
        books = {r[0] for r in cur.fetchall()}
        assert books <= {"Market", "Discovery"}, f"private book leaked: {books}"

    def test_approved_claimant_sees_their_book(self, cur):
        as_user(cur, email="steven@saaicoenergy.com")
        cur.execute("""select distinct jsonb_array_elements(get_bid_sheet()->'valuations')->>'book'""")
        books = {r[0] for r in cur.fetchall()}
        assert "Saaico 2027 First" in books


class TestArtifactsPolicy:
    def test_anon_cannot_read_ref_artifacts(self, cur):
        cur.execute("set local role anon")
        cur.execute("select count(*) from artifacts where name like 'ref/%'")
        assert cur.fetchone()[0] == 0

    def test_anon_reads_page_artifacts(self, cur):
        cur.execute("set local role anon")
        cur.execute("select count(*) from artifacts where name = 'node_graph'")
        assert cur.fetchone()[0] == 1


class TestClaimHolder:
    def test_no_server_secret_returns_no_token(self, cur):
        as_user(cur, uid=STRANGER)
        cur.execute("insert into auth.users (id, email) values (%s, 'pgtest@example.com')",
                    (STRANGER,))
        cur.execute("select claim_holder('XSAAIC', null)")
        res = cur.fetchone()[0]
        assert "token" not in res, "verification token leaked without server secret"

    def test_single_overload_only(self, cur):
        cur.execute("select count(*) from pg_proc where proname = 'claim_holder'")
        assert cur.fetchone()[0] == 1, "the pre-lockdown 1-arg overload is back"


class TestPlanEnforcement:
    def test_expired_trial_is_locked_out(self, cur):
        uid = as_user(cur, email="viswise+uxwalk@gmail.com")
        cur.execute("update profiles set plan='trial', trial_ends=current_date-1 where user_id=%s",
                    (uid,))
        cur.execute("select get_bid_sheet()")
        assert cur.fetchone()[0] is None

    def test_live_trial_passes(self, cur):
        uid = as_user(cur, email="viswise+uxwalk@gmail.com")
        cur.execute("update profiles set plan='trial', trial_ends=current_date+1 where user_id=%s",
                    (uid,))
        cur.execute("select jsonb_array_length(get_bid_sheet()->'valuations')")
        assert cur.fetchone()[0] > 0

    def test_admin_always_passes(self, cur):
        as_user(cur, email="viswise@gmail.com")
        cur.execute("select get_bid_sheet() is not null")
        assert cur.fetchone()[0]


class TestSqlCalendar:
    @pytest.mark.parametrize("d,he,want", [
        ("2026-09-07", 12, "PeakWE"),   # Labor Day
        ("2026-09-08", 12, "PeakWD"),
        ("2026-07-03", 12, "PeakWD"),   # Sat holiday NOT substituted to Friday
        ("2027-07-05", 12, "PeakWE"),   # Sun holiday observed Monday
        ("2026-09-08", 23, "Off-peak"),
    ])
    def test_matches_python_calendar(self, cur, d, he, want):
        cur.execute("select crr_time_of_use(%s::date, %s)", (d, he))
        assert cur.fetchone()[0] == want
        import datetime as dt
        import sys
        sys.path.insert(0, str(ROOT))
        from ercot.calendar import tou_of
        assert tou_of(dt.date.fromisoformat(d), he) == want


class TestSnapshotImmutability:
    def test_sheet_rows_reject_identity_edits(self, cur):
        cur.execute("select id from sheet_snapshots limit 1")
        rid = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute("update sheet_snapshots set ref_limit = 999 where id = %s", (rid,))

    def test_sheet_rows_reject_delete(self, cur):
        cur.execute("select id from sheet_snapshots limit 1")
        rid = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.RaiseException):
            cur.execute("delete from sheet_snapshots where id = %s", (rid,))


class TestRevisionTrigger:
    def test_price_revision_is_recorded(self, cur):
        cur.execute("""insert into dam_spp (settlement_point, delivery_date, hour_ending,
                                            interval_start, price)
                       values ('PGTEST_NODE', '2030-01-15', 1, '2030-01-15 06:00+00', 10.0)""")
        cur.execute("""update dam_spp set price = 12.5
                        where settlement_point='PGTEST_NODE' and delivery_date='2030-01-15'""")
        cur.execute("""select count(*) from dam_spp_history
                        where settlement_point = 'PGTEST_NODE'""")
        n = cur.fetchone()[0]
        assert n >= 1, "price change left no revision-history row"
