"""Shared Google token refresh logic. Called by gmail.py and calendar.py."""
import json
import os
import time

import requests


def get_valid_token() -> str:
    """Return a valid access token, refreshing if needed."""
    access_token = os.environ.get("GOOGLE_ACCESS_TOKEN", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if not refresh_token:
        raise RuntimeError("GOOGLE_REFRESH_TOKEN not set. Connect Google in your NoDesk portal.")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set.")

    # Always refresh to get a guaranteed-valid token.
    # Google refresh tokens are long-lived; access tokens expire in 1 hour.
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    new_token = data.get("access_token")
    if not new_token:
        raise RuntimeError(f"Token refresh failed: {data}")

    # Write back to env for this process lifetime.
    os.environ["GOOGLE_ACCESS_TOKEN"] = new_token
    return new_token
