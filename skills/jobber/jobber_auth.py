#!/usr/bin/env python3
"""
Jobber OAuth + GraphQL transport — shared by jobber_lookup.py and jobber_write.py.

Jobber's API is GraphQL only:
    POST https://api.getjobber.com/api/graphql
with headers:
    Authorization: Bearer <access_token>
    Content-Type: application/json
    X-JOBBER-GRAPHQL-VERSION: <YYYY-MM-DD>   (REQUIRED schema pin)

The agent populates these from the environment (NoDesk pushes them at
credential-sync time); there is NO Jobber username/password:
    JOBBER_ACCESS_TOKEN     Bearer token (expires in ~60 minutes)
    JOBBER_REFRESH_TOKEN    long-lived refresh token
    JOBBER_CLIENT_ID        app client id
    JOBBER_CLIENT_SECRET    app client secret
    JOBBER_GRAPHQL_VERSION  optional override of the pinned schema date

Because the access token expires after ~60 minutes, this module self-refreshes:
on a 401 (or an auth/THROTTLED GraphQL error) it POSTs to the token endpoint
with grant_type=refresh_token, caches the fresh access token to
jobber_tokens.json (chmod 600) in the skill dir, and retries the request once.

This file is import-only (no CLI); the lookup/write scripts call run_query().
"""

import json
import os
import sys
import time

import requests

try:
    from dotenv import load_dotenv
    from pathlib import Path
    # Hermes may export JOBBER_* in the gateway env; an .env file may also exist.
    load_dotenv(Path.home() / ".hermes" / ".env", override=False)
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.path.join(SKILL_DIR, "jobber_tokens.json")

GRAPHQL_URL = "https://api.getjobber.com/api/graphql"
TOKEN_URL = "https://api.getjobber.com/api/oauth/token"

# Pinned schema version. Jobber REQUIRES this header. This date may need
# updating over time; `jobber_lookup.py introspect` reveals the live schema,
# and JOBBER_GRAPHQL_VERSION overrides this default.
DEFAULT_GRAPHQL_VERSION = "2025-01-20"

TIMEOUT = 30


def graphql_version() -> str:
    return os.environ.get("JOBBER_GRAPHQL_VERSION") or DEFAULT_GRAPHQL_VERSION


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def _load_tokens() -> dict:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE) as f:
                return json.load(f)
        except (ValueError, OSError):
            return {}
    return {}


def _save_tokens(data: dict) -> None:
    try:
        with open(TOKENS_FILE, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(TOKENS_FILE, 0o600)
    except OSError:
        pass  # caching is best-effort; a read-only FS shouldn't break the call


def _current_access_token() -> str:
    """Prefer a freshly-cached token over the (possibly stale) env token."""
    cached = _load_tokens().get("access_token")
    if cached:
        return cached
    return os.environ.get("JOBBER_ACCESS_TOKEN", "").strip()


def _refresh_token_value() -> str:
    # A refresh token cached after a previous refresh wins over the env one.
    return (
        _load_tokens().get("refresh_token")
        or os.environ.get("JOBBER_REFRESH_TOKEN", "").strip()
    )


def _ensure_have_token() -> None:
    if not _current_access_token() and not _refresh_token_value():
        print(
            "error: no Jobber access token and no refresh token — "
            "connect Jobber in the NoDesk portal.",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def _refresh_access_token() -> str:
    """Exchange the refresh token for a new access token; cache it; return it."""
    refresh = _refresh_token_value()
    client_id = os.environ.get("JOBBER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("JOBBER_CLIENT_SECRET", "").strip()
    if not refresh:
        print(
            "error: Jobber access token expired and no refresh token available — "
            "reconnect Jobber in the NoDesk portal.",
            file=sys.stderr,
        )
        sys.exit(3)
    if not client_id or not client_secret:
        print(
            "error: cannot refresh Jobber token — JOBBER_CLIENT_ID / "
            "JOBBER_CLIENT_SECRET missing. Reconnect Jobber in the NoDesk portal.",
            file=sys.stderr,
        )
        sys.exit(3)

    resp = requests.post(
        TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code >= 400:
        print(
            f"error: Jobber token refresh failed ({resp.status_code}): "
            f"{resp.text[:300]} — reconnect Jobber in the NoDesk portal.",
            file=sys.stderr,
        )
        sys.exit(3)
    try:
        data = resp.json()
    except ValueError:
        print("error: Jobber token refresh returned non-JSON.", file=sys.stderr)
        sys.exit(3)

    access = data.get("access_token")
    if not access:
        print(f"error: Jobber token refresh returned no access_token: {data}", file=sys.stderr)
        sys.exit(3)

    cache = _load_tokens()
    cache["access_token"] = access
    # Jobber may rotate the refresh token; keep the newest one.
    if data.get("refresh_token"):
        cache["refresh_token"] = data["refresh_token"]
    cache["obtained_at"] = int(time.time())
    if data.get("expires_in"):
        cache["expires_in"] = data["expires_in"]
    _save_tokens(cache)
    return access


# ---------------------------------------------------------------------------
# GraphQL transport
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-JOBBER-GRAPHQL-VERSION": graphql_version(),
    }


def _looks_like_auth_error(payload: dict) -> bool:
    """Detect auth/throttle signals inside a 200-with-errors GraphQL body."""
    for err in payload.get("errors", []) or []:
        msg = (err.get("message") or "").upper()
        code = ((err.get("extensions") or {}).get("code") or "").upper()
        if "THROTTLED" in code or "THROTTLED" in msg:
            return True
        if "UNAUTHENTICATED" in code or "UNAUTHORIZED" in code:
            return True
        if "NOT AUTHORIZED" in msg or "UNAUTHENTICATED" in msg or "EXPIRED" in msg:
            return True
    return False


def _post_graphql(token: str, query: str, variables: dict | None) -> requests.Response:
    body = {"query": query}
    if variables:
        body["variables"] = variables
    return requests.post(GRAPHQL_URL, headers=_headers(token), json=body, timeout=TIMEOUT)


def run_query(query: str, variables: dict | None = None) -> dict:
    """
    Execute a GraphQL query/mutation, refreshing the token + retrying once on
    auth failure. Returns the parsed JSON body (the caller inspects `data` and
    `errors`). Exits non-zero on hard transport / auth failures.
    """
    _ensure_have_token()
    token = _current_access_token()

    # If we somehow have only a refresh token (no access token), get one first.
    if not token:
        token = _refresh_access_token()

    resp = _post_graphql(token, query, variables)

    # HTTP-level rate limit.
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "")
        print(
            "error: 429 Too Many Requests — Jobber rate limit"
            + (f" (retry after {retry}s)" if retry else "")
            + ". Wait and retry.",
            file=sys.stderr,
        )
        sys.exit(5)

    # HTTP-level auth failure -> refresh + retry once.
    if resp.status_code == 401:
        token = _refresh_access_token()
        resp = _post_graphql(token, query, variables)
        if resp.status_code == 401:
            print(
                "error: 401 Unauthorized after refresh — reconnect Jobber in the NoDesk portal.",
                file=sys.stderr,
            )
            sys.exit(3)

    if resp.status_code >= 400:
        print(f"error: Jobber HTTP {resp.status_code}: {resp.text[:400]}", file=sys.stderr)
        sys.exit(1)

    try:
        payload = resp.json()
    except ValueError:
        print(f"error: Jobber returned non-JSON: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)

    # GraphQL 200-with-errors that smell like auth/throttle -> refresh + retry once.
    if payload.get("errors") and _looks_like_auth_error(payload):
        token = _refresh_access_token()
        resp = _post_graphql(token, query, variables)
        if resp.status_code >= 400:
            print(f"error: Jobber HTTP {resp.status_code} after refresh: {resp.text[:300]}", file=sys.stderr)
            sys.exit(1)
        try:
            payload = resp.json()
        except ValueError:
            print(f"error: Jobber returned non-JSON after refresh: {resp.text[:300]}", file=sys.stderr)
            sys.exit(1)

    return payload
