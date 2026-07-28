"""Field mapping, paging and throttle behaviour, against a mock transport."""

from __future__ import annotations

import httpx
import pytest

from ercot import config
from ercot.client import ErcotClient, ErcotError, RateLimiter, field


class TestField:
    def test_matches_case_insensitively(self):
        assert field({"SettlementPoint": "HB_NORTH"}, "settlementPoint") == "HB_NORTH"

    def test_tries_candidates_in_order(self):
        assert field({"spp": 42.0}, "settlementPointPrice", "spp", "price") == 42.0

    def test_skips_empty_values(self):
        # A present-but-blank column must not shadow a later candidate.
        assert field({"settlementPointPrice": "", "price": 12.5},
                     "settlementPointPrice", "price") == 12.5

    def test_returns_default_when_absent(self):
        assert field({"a": 1}, "b", default="fallback") == "fallback"

    def test_tolerates_none_keys(self):
        assert field({None: 1, "price": 3.0}, "price") == 3.0


def make_client(handler) -> ErcotClient:
    client = ErcotClient()
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    client._token = "test-token"
    client._token_expires_at = float("inf")
    return client


def page(fields, data, total_pages=1):
    return {
        "fields": [{"name": f} for f in fields],
        "data": data,
        "_meta": {"totalPages": total_pages},
    }


@pytest.fixture(autouse=True)
def _subscription_key(monkeypatch):
    monkeypatch.setenv("ERCOT_SUBSCRIPTION_KEY", "test-key")


class TestPaging:
    def test_zips_fields_to_dicts(self):
        client = make_client(lambda req: httpx.Response(
            200, json=page(["settlementPoint", "price"], [["HB_NORTH", 30.0]])))
        assert list(client.rows("/x", {})) == [{"settlementPoint": "HB_NORTH", "price": 30.0}]

    def test_follows_total_pages(self):
        seen = []

        def handler(request):
            page_num = int(request.url.params.get("page", 1))
            seen.append(page_num)
            return httpx.Response(200, json=page(
                ["settlementPoint"], [[f"P{page_num}"]], total_pages=3))

        rows = list(make_client(handler).rows("/x", {}))
        assert seen == [1, 2, 3]
        assert [r["settlementPoint"] for r in rows] == ["P1", "P2", "P3"]

    def test_stops_on_empty_data(self):
        client = make_client(lambda req: httpx.Response(
            200, json=page(["settlementPoint"], [], total_pages=5)))
        assert list(client.rows("/x", {})) == []

    def test_page_cap_raises_rather_than_truncating(self, monkeypatch):
        """A short window must not look like a quiet period.

        Every row that arrives before the cap is valid, so nothing downstream
        can tell that the rest is missing. This silently loaded 26% of the
        day-ahead map and reported success on every window.
        """
        monkeypatch.setattr(config, "MAX_PAGES", 2)
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json=page(["settlementPoint"], [["P"]], total_pages=99))

        with pytest.raises(ErcotError, match="page cap"):
            list(make_client(handler).rows("/x", {}))
        assert len(calls) == 2


class TestRetries:
    def test_retries_on_500_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(config, "BACKOFF_BASE_SECONDS", 0.0)
        attempts = []

        def handler(request):
            attempts.append(1)
            if len(attempts) < 3:
                return httpx.Response(500, text="upstream error")
            return httpx.Response(200, json=page(["a"], [["ok"]]))

        assert list(make_client(handler).rows("/x", {})) == [{"a": "ok"}]
        assert len(attempts) == 3

    def test_honours_retry_after_on_429(self, monkeypatch):
        slept = []
        monkeypatch.setattr("ercot.client.time.sleep", lambda s: slept.append(s))
        attempts = []

        def handler(request):
            attempts.append(1)
            if len(attempts) == 1:
                return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
            return httpx.Response(200, json=page(["a"], [["ok"]]))

        list(make_client(handler).rows("/x", {}))
        assert 7.0 in slept

    def test_gives_up_after_max_retries(self, monkeypatch):
        monkeypatch.setattr(config, "BACKOFF_BASE_SECONDS", 0.0)
        client = make_client(lambda req: httpx.Response(503, text="down"))
        with pytest.raises(ErcotError, match="after"):
            list(client.rows("/x", {}))

    def test_client_error_is_not_retried(self):
        attempts = []

        def handler(request):
            attempts.append(1)
            return httpx.Response(400, text="bad parameter")

        with pytest.raises(ErcotError, match="400"):
            list(make_client(handler).rows("/x", {}))
        assert len(attempts) == 1


class TestRateLimiter:
    def test_allows_up_to_the_limit_without_sleeping(self, monkeypatch):
        slept = []
        monkeypatch.setattr("ercot.client.time.sleep", lambda s: slept.append(s))
        limiter = RateLimiter(per_minute=3)
        for _ in range(3):
            limiter.acquire()
        assert slept == []

    def test_sleeps_once_the_window_is_full(self, monkeypatch):
        slept = []
        clock = {"now": 0.0}

        def fake_sleep(seconds):
            slept.append(seconds)
            clock["now"] = 1000.0  # advance past the window

        monkeypatch.setattr("ercot.client.time.monotonic", lambda: clock["now"])
        monkeypatch.setattr("ercot.client.time.sleep", fake_sleep)

        limiter = RateLimiter(per_minute=2)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        assert len(slept) == 1
