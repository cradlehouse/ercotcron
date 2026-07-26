#!/usr/bin/env python3
"""Print an endpoint's real parameter and field names.

The five-minute jobs are the risky ones: a wrong query parameter name does not
raise, it returns zero rows. Run this before trusting a green cron.

    python scripts/describe_endpoint.py /np6-788-cd/lmp_node_zone_hub
    python scripts/describe_endpoint.py /np6-970-cd/rtd_lmp_node_zone_hub
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from ercot import config  # noqa: E402
from ercot.client import ErcotClient, ErcotError  # noqa: E402


def describe_response_fields(client: ErcotClient, endpoint: str) -> None:
    """The response's own `fields` block is the authoritative column list."""
    print(f"\n=== response fields for {endpoint} ===")
    try:
        payload = client.get(endpoint, {"page": 1, "size": 1})
    except ErcotError as exc:
        print(f"  request failed: {exc}")
        return

    fields = payload.get("fields") or []
    if not fields:
        print("  no fields returned (the endpoint may need a date filter to return anything)")
    for f in fields:
        print(f"  {f.get('name'):<40} {f.get('dataType', '')}")

    meta = payload.get("_meta") or {}
    if meta:
        print(f"\n  _meta: {meta}")

    data = payload.get("data") or []
    if data and fields:
        print("\n  sample row:")
        for name, value in zip([f.get("name") for f in fields], data[0]):
            print(f"    {name:<40} {value!r}")


def describe_parameters(client: ErcotClient, endpoint: str) -> None:
    """Ask ERCOT's OpenAPI document for the accepted query parameters."""
    print(f"\n=== query parameters for {endpoint} ===")

    candidates = [
        f"{config.BASE_URL}/openapi.json",
        f"{config.BASE_URL}/swagger/v1/swagger.json",
        "https://api.ercot.com/api/public-reports/openapi",
    ]
    headers = {
        "Ocp-Apim-Subscription-Key": config.ercot_subscription_key(),
        "Authorization": f"Bearer {client.token()}",
        "Accept": "application/json",
    }

    for url in candidates:
        try:
            resp = httpx.get(url, headers=headers, timeout=60.0)
        except httpx.HTTPError:
            continue
        if resp.status_code != 200:
            continue
        try:
            spec = resp.json()
        except ValueError:
            continue

        paths = spec.get("paths") or {}
        match = paths.get(endpoint) or paths.get(f"/api/public-reports{endpoint}")
        if not match:
            # Endpoint keys sometimes carry a prefix; fall back to a suffix match.
            match = next(
                (v for k, v in paths.items() if k.rstrip("/").endswith(endpoint.rstrip("/"))),
                None,
            )
        if not match:
            continue

        print(f"  (from {url})")
        for method, spec_body in match.items():
            if not isinstance(spec_body, dict):
                continue
            for param in spec_body.get("parameters") or []:
                name = param.get("name")
                where = param.get("in", "")
                ptype = (param.get("schema") or {}).get("type", "")
                print(f"  {name:<40} {where:<8} {ptype}")
        return

    print(
        "  Could not retrieve an OpenAPI document.\n"
        "  Fall back to the browsable spec at https://apiexplorer.ercot.com — open the\n"
        f"  product for {endpoint} and read the query parameters there.\n"
        "  The response fields above still confirm the column names."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="e.g. /np6-788-cd/lmp_node_zone_hub")
    args = parser.parse_args()

    endpoint = args.endpoint if args.endpoint.startswith("/") else f"/{args.endpoint}"
    client = ErcotClient()

    describe_parameters(client, endpoint)
    describe_response_fields(client, endpoint)

    print(
        "\nIf a parameter name here differs from the constants in ercot/ingest.py, "
        "fix ingest.py — a wrong name returns zero rows rather than an error."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
