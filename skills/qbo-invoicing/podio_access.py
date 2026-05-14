"""
Shared Podio OAuth for Hermes skills.

Priority:
1. PODIO_ACCESS_TOKEN from ~/.hermes/.env (set by NoDesk credential sync)
2. Refresh using PODIO_REFRESH_TOKEN + client id/secret if access token missing
3. Legacy password grant (PODIO_USERNAME / PODIO_PASSWORD)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

PODIO_TOKEN_URL = "https://podio.com/oauth/token"
TIMEOUT = 15

_cache: dict = {"access_token": None, "expires_at": 0.0}


def load_hermes_env() -> None:
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _strip(v: str | None) -> str:
    return (v or "").strip().strip("'\"")


def _refresh_access_token() -> str:
    load_hermes_env()
    refresh = _strip(os.environ.get("PODIO_REFRESH_TOKEN"))
    cid = _strip(os.environ.get("PODIO_CLIENT_ID"))
    secret = _strip(os.environ.get("PODIO_CLIENT_SECRET"))
    if not refresh or not cid or not secret:
        raise RuntimeError("Podio refresh_token or client credentials missing")
    resp = requests.post(
        PODIO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": cid,
            "client_secret": secret,
            "refresh_token": refresh,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Podio token refresh failed ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def _password_grant_token() -> str:
    load_hermes_env()
    required = ["PODIO_CLIENT_ID", "PODIO_CLIENT_SECRET", "PODIO_USERNAME", "PODIO_PASSWORD"]
    missing = [k for k in required if not _strip(os.environ.get(k))]
    if missing:
        raise RuntimeError(f"Missing Podio env vars: {', '.join(missing)}")
    resp = requests.post(
        PODIO_TOKEN_URL,
        data={
            "grant_type": "password",
            "client_id": _strip(os.environ["PODIO_CLIENT_ID"]),
            "client_secret": _strip(os.environ["PODIO_CLIENT_SECRET"]),
            "username": _strip(os.environ["PODIO_USERNAME"]),
            "password": _strip(os.environ["PODIO_PASSWORD"]),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Podio password auth failed ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def get_podio_access_token() -> str:
    """Return a Bearer token for api.podio.com (OAuth2 header)."""
    now = time.time()
    if _cache["access_token"] and _cache["expires_at"] - now > 60:
        return _cache["access_token"]

    load_hermes_env()
    access = _strip(os.environ.get("PODIO_ACCESS_TOKEN"))
    if access:
        _cache["access_token"] = access
        _cache["expires_at"] = now + 3300
        return access

    try:
        token = _refresh_access_token()
    except RuntimeError:
        token = _password_grant_token()

    _cache["access_token"] = token
    _cache["expires_at"] = now + 3300
    return token


def get_podio_access_token_or_none() -> str | None:
    try:
        return get_podio_access_token()
    except RuntimeError as exc:
        print(f"{exc}", file=sys.stderr)
        return None
