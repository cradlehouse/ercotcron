"""Environment, endpoints and pacing constants."""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# ERCOT publishes on a Central clock. Every conversion between a delivery date /
# hour ending and a real instant goes through this zone.
CENTRAL = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


def _req(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ------------------------------------------------------------ credentials --

# Read lazily so importing the package never requires a configured environment —
# tests and describe_endpoint.py import freely.


def ercot_username() -> str:
    return _req("ERCOT_USERNAME")


def ercot_password() -> str:
    return _req("ERCOT_PASSWORD")


def ercot_subscription_key() -> str:
    # Never fail over to the secondary subscription key at runtime. Both keys
    # share one quota and one suspension status; the secondary exists only so a
    # key can be rotated without downtime.
    return _req("ERCOT_SUBSCRIPTION_KEY")


def database_url() -> str:
    return _req("DATABASE_URL")


def trigger_secret() -> str:
    return _opt("TRIGGER_SECRET")


def heartbeat_url(job: str) -> str:
    """Optional per-job heartbeat ping (healthchecks.io or similar)."""
    return _opt(f"HEARTBEAT_URL_{job.upper()}")

# ---------------------------------------------------------------- ERCOT API --

AUTH_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBLIC-API-ROPC/oauth2/v2.0/token"
)
AUTH_CLIENT_ID = "fec7d00d-778b-4d24-a2eb-4b12e0a20a86"

BASE_URL = "https://api.ercot.com/api/public-reports"

# Endpoints actually ingested.
EP_DAM_SPP = "/np4-190-cd/dam_stlmnt_pnt_prices"
EP_RT_SPP = "/np6-905-cd/spp_node_zone_hub"
EP_LMP_5MIN = "/np6-788-cd/lmp_node_zone_hub"
EP_RTD_LMP = "/np6-970-cd/rtd_lmp_node_zone_hub"

# Deliberately not ingested: /np6-787-cd/lmp_electrical_bus is roughly 13k buses
# every five minutes, 1.4B rows a year, and is the endpoint behind most of the
# public throttling complaints.

# ------------------------------------------------------------------ pacing --

PAGE_SIZE = 5_000            # ERCOT caps page size at 1,000,000 but paces on volume
MAX_PAGES = 40               # a single job should never need more
REQUESTS_PER_MINUTE = 24     # ERCOT allows 30; leave headroom for retries
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 2.0
HTTP_TIMEOUT_SECONDS = 60.0

# Token lifetime is about an hour; refresh early rather than racing expiry.
TOKEN_REFRESH_MARGIN_SECONDS = 300
