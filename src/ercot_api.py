"""
ERCOT Public API client for Step 0.

What this does, in plain terms:
  1. Logs in to ERCOT (exchanges your username/password for a 1-hour token).
  2. Fetches a "report" (a data series) from the public API, following
     pagination so we never silently get a truncated page.
  3. Has a `probe` mode you run FIRST to confirm the exact NP6-331-CD endpoint
     path and print the real column names (we never assume them).

Credentials come from the .env file (loaded via python-dotenv). Nothing secret
is hard-coded here.

Reference: CLAUDE.md "Environment and API notes".
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()  # read .env into environment variables

# --- constants from CLAUDE.md ------------------------------------------------
TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
BASE_URL = "https://api.ercot.com/api/public-reports"

USERNAME = os.getenv("ERCOT_API_USERNAME")
PASSWORD = os.getenv("ERCOT_API_PASSWORD")
PUBLIC_KEY = os.getenv("ERCOT_PUBLIC_API_SUBSCRIPTION_KEY")


class ErcotAuthError(RuntimeError):
    pass


def get_token() -> str:
    """Log in and return the bearer token string.

    ERCOT's docs are inconsistent about whether the id_token or access_token is
    the right bearer value, so we return id_token and let the caller fall back
    to access_token on a 401 (see `request`).
    """
    if not (USERNAME and PASSWORD and PUBLIC_KEY):
        raise ErcotAuthError(
            "Missing credentials. Copy .env.example to .env and fill in "
            "ERCOT_API_USERNAME, ERCOT_API_PASSWORD, "
            "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY."
        )
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "password",
            "username": USERNAME,
            "password": PASSWORD,
            "client_id": CLIENT_ID,
            "scope": f"openid {CLIENT_ID} offline_access",
            "response_type": "id_token",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise ErcotAuthError(
            f"Token request failed ({resp.status_code}): {resp.text[:400]}"
        )
    body = resp.json()
    # keep both so `request` can fall back
    global _ACCESS_TOKEN
    _ACCESS_TOKEN = body.get("access_token")
    token = body.get("id_token") or body.get("access_token")
    if not token:
        raise ErcotAuthError(f"No token in response: {list(body)}")
    return token


_ACCESS_TOKEN: str | None = None
_TOKEN_CACHE: dict[str, Any] = {"token": None, "issued": 0.0}


def _current_token() -> str:
    """Return a cached token, refreshing if older than ~55 minutes."""
    if _TOKEN_CACHE["token"] is None or (time.time() - _TOKEN_CACHE["issued"]) > 55 * 60:
        _TOKEN_CACHE["token"] = get_token()
        _TOKEN_CACHE["issued"] = time.time()
    return _TOKEN_CACHE["token"]


def request(path: str, params: dict | None = None, max_429: int = 6) -> requests.Response:
    """GET a single page from the public-reports API.

    `path` is everything after BASE_URL, e.g. "/np6-905-cd/spp_node_zone_hub".
    Handles the id_token/access_token ambiguity by retrying once with the
    access_token on a 401, and honours ERCOT's rate limit: on a 429 it sleeps the
    cooldown ERCOT reports ("Try again in N seconds") and retries.
    """
    import re
    url = BASE_URL + path
    headers = {
        "Authorization": f"Bearer {_current_token()}",
        "Ocp-Apim-Subscription-Key": PUBLIC_KEY,
    }
    for _ in range(max_429 + 1):
        resp = requests.get(url, headers=headers, params=params or {}, timeout=120)
        if resp.status_code == 401 and _ACCESS_TOKEN:
            headers["Authorization"] = f"Bearer {_ACCESS_TOKEN}"
            resp = requests.get(url, headers=headers, params=params or {}, timeout=120)
        if resp.status_code == 429:
            m = re.search(r"(\d+)\s*second", resp.text)
            time.sleep(min((int(m.group(1)) + 2) if m else 15, 60))
            continue
        return resp
    return resp


def get_report(path: str, params: dict | None = None, page_size: int = 1000) -> dict:
    """Fetch ALL pages of a report and return {"fields": [...], "data": [...]}.

    ERCOT paginates and truncates silently, so we loop until we've collected
    every page and assert the row count matches the reported total.
    """
    params = dict(params or {})
    params["size"] = page_size
    params["page"] = 1

    first = request(path, params)
    if first.status_code != 200:
        raise RuntimeError(
            f"GET {path} failed ({first.status_code}): {first.text[:600]}"
        )
    body = first.json()
    fields = body.get("fields", [])
    rows = list(body.get("data", []))
    meta = body.get("_meta", {}) or {}
    total_pages = meta.get("totalPages", 1)
    total_records = meta.get("totalRecords", len(rows))

    for page in range(2, int(total_pages) + 1):
        params["page"] = page
        r = request(path, params)
        r.raise_for_status()
        rows.extend(r.json().get("data", []))
        time.sleep(0.05)  # be gentle

    if total_records and len(rows) != total_records:
        print(
            f"  WARNING: collected {len(rows)} rows but _meta says "
            f"{total_records}. Investigate pagination before trusting this.",
            file=sys.stderr,
        )
    return {"fields": fields, "data": rows, "meta": meta}


# --- probe mode: run this FIRST to confirm endpoints/columns -----------------
CANDIDATE_MCPC_PATHS = [
    # NP6-331-CD "Real-Time Clearing Prices for Capacity by 15-min interval".
    # We do not know the exact subpath; probe several plausible ones and report
    # which returns 200. DO NOT hard-code the winner until we've seen it work.
    "/np6-331-cd/rt_clr_price_cap",
    "/np6-331-cd/rt_clearing_prices_capacity",
    "/np6-331-cd",
]
SPP_PATH = "/np6-905-cd/spp_node_zone_hub"


def _probe(path: str, params: dict | None = None) -> None:
    print(f"\n--- PROBE {path}  params={params or {}}")
    try:
        r = request(path, {**(params or {}), "size": 5, "page": 1})
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: {e}")
        return
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        fields = [f.get("name") for f in body.get("fields", [])]
        print(f"  fields: {fields}")
        data = body.get("data", [])
        print(f"  first row: {data[0] if data else '(none)'}")
        print(f"  _meta: {body.get('_meta')}")
    else:
        print(f"  body: {r.text[:400]}")


if __name__ == "__main__":
    # Smoke check: authenticate, then probe both series.
    print("Authenticating...")
    _current_token()
    print("OK, token acquired.")

    _probe(SPP_PATH)
    for p in CANDIDATE_MCPC_PATHS:
        _probe(p)
    print(
        "\nNext: whichever MCPC path returned status 200 with price columns is "
        "the real NP6-331-CD endpoint. Tell Claude which one, and note the "
        "date-filter parameter names from the fields list."
    )
