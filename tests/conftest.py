import pytest

from ercot import client as client_module


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Neutralise the shared rate limiter.

    It is process-wide, so without this the mocked requests across the suite
    trip the real 24-per-minute window and the tests sit in a genuine sleep.
    TestRateLimiter exercises the limiter directly on its own instance.
    """
    monkeypatch.setattr(client_module._limiter, "acquire", lambda: None)
