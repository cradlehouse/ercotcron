"""ERCOT Public API client: ROPC auth, request pacing, paging, 429 backoff.

The public-reports API returns rows column-wise — a `fields` list describing the
columns and a `data` list of positional arrays. This module turns that into
dicts so callers never depend on column order, and `field()` looks names up
case-insensitively because ERCOT's casing drifts between reports.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Iterator

import httpx

from . import config

log = logging.getLogger(__name__)


class ErcotError(RuntimeError):
    """A request failed after exhausting retries."""


class RateLimiter:
    """Sliding-window limiter shared by every job in the process."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] > 60.0:
                    self._calls.popleft()
                if len(self._calls) < self._per_minute:
                    self._calls.append(now)
                    return
                wait = 60.0 - (now - self._calls[0]) + 0.05
            log.debug("rate limiter sleeping %.2fs", wait)
            time.sleep(wait)


_limiter = RateLimiter(config.REQUESTS_PER_MINUTE)


class ErcotClient:
    """One client per process. Caches the bearer token across all jobs."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=config.HTTP_TIMEOUT_SECONDS)
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

    # ------------------------------------------------------------- auth --

    def _fetch_token(self) -> tuple[str, float]:
        data = {
            "username": config.ercot_username(),
            "password": config.ercot_password(),
            "grant_type": "password",
            "scope": f"openid {config.AUTH_CLIENT_ID} offline_access",
            "client_id": config.AUTH_CLIENT_ID,
            "response_type": "id_token",
        }
        resp = self._http.post(config.AUTH_URL, data=data)
        if resp.status_code != 200:
            raise ErcotError(f"auth failed ({resp.status_code}): {resp.text[:400]}")
        payload = resp.json()
        token = payload.get("id_token") or payload.get("access_token")
        if not token:
            raise ErcotError(f"auth response contained no token: {list(payload)}")
        # ERCOT reports expires_in in seconds; default to an hour if absent.
        ttl = float(payload.get("expires_in") or 3600)
        return token, time.monotonic() + ttl - config.TOKEN_REFRESH_MARGIN_SECONDS

    def token(self) -> str:
        with self._token_lock:
            if self._token is None or time.monotonic() >= self._token_expires_at:
                log.info("fetching ERCOT bearer token")
                self._token, self._token_expires_at = self._fetch_token()
            return self._token

    def _invalidate_token(self) -> None:
        with self._token_lock:
            self._token = None
            self._token_expires_at = 0.0

    # --------------------------------------------------------- requests --

    def get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{config.BASE_URL}{endpoint}"
        last_error = ""

        for attempt in range(config.MAX_RETRIES):
            _limiter.acquire()
            headers = {
                "Authorization": f"Bearer {self.token()}",
                "Ocp-Apim-Subscription-Key": config.ercot_subscription_key(),
                "Accept": "application/json",
            }
            try:
                resp = self._http.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"transport error: {exc}"
                self._sleep_backoff(attempt)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (401, 403):
                # Token may have been revoked early; refresh once, then treat as fatal.
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                self._invalidate_token()
                if attempt == 0:
                    continue
                raise ErcotError(f"{endpoint} auth rejected — {last_error}")

            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                last_error = f"{resp.status_code}: {resp.text[:300]}"
                if retry_after and retry_after.isdigit():
                    log.warning("%s throttled, honouring Retry-After=%ss", endpoint, retry_after)
                    time.sleep(float(retry_after))
                else:
                    self._sleep_backoff(attempt)
                continue

            raise ErcotError(f"{endpoint} failed ({resp.status_code}): {resp.text[:400]}")

        raise ErcotError(f"{endpoint} failed after {config.MAX_RETRIES} attempts — {last_error}")

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        delay = config.BACKOFF_BASE_SECONDS * (2**attempt)
        log.warning("retrying in %.1fs (attempt %d)", delay, attempt + 1)
        time.sleep(delay)

    # ------------------------------------------------------------ paging --

    def rows(self, endpoint: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yield every row across pages as a dict keyed by ERCOT's field names."""
        page = 1
        while page <= config.MAX_PAGES:
            payload = self.get(endpoint, {**params, "page": page, "size": config.PAGE_SIZE})
            fields = [f.get("name") for f in payload.get("fields") or []]
            data = payload.get("data") or []
            if not fields or not data:
                return

            for row in data:
                yield dict(zip(fields, row))

            meta = payload.get("_meta") or {}
            total_pages = meta.get("totalPages")
            if total_pages is None:
                if len(data) < config.PAGE_SIZE:
                    return
            elif page >= int(total_pages):
                return
            page += 1

        log.warning("%s hit the %d page cap — window is too wide", endpoint, config.MAX_PAGES)

    def request_count_estimate(self, row_count: int) -> int:
        return max(1, -(-row_count // config.PAGE_SIZE))


def field(row: dict[str, Any], *candidates: str, default: Any = None) -> Any:
    """Case-insensitive lookup across candidate names.

    ERCOT's field casing drifts between reports; a column that lands null in the
    database usually means the real name belongs in this call.
    """
    lowered = {k.lower(): v for k, v in row.items() if k}
    for name in candidates:
        if name.lower() in lowered:
            value = lowered[name.lower()]
            if value is not None and value != "":
                return value
    return default
