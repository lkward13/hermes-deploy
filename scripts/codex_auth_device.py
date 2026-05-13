#!/usr/bin/env python3
"""Start and complete OpenAI Codex device auth for Hermes Telegram users."""

from __future__ import annotations

import argparse
import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ISSUER = "https://auth.openai.com"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _pending_path() -> Path:
    return _hermes_home() / "credentials" / "codex_auth_pending.json"


def _auth_path() -> Path:
    return _hermes_home() / "auth.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_private_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _request_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    response = requests.request(method, url, timeout=15, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{url} returned HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} returned an unexpected response")
    return payload


def start_auth(_args: argparse.Namespace) -> int:
    payload = _request_json(
        "POST",
        f"{ISSUER}/api/accounts/deviceauth/usercode",
        json={"client_id": CODEX_OAUTH_CLIENT_ID},
        headers={"Content-Type": "application/json"},
    )

    user_code = str(payload.get("user_code") or "").strip()
    device_auth_id = str(payload.get("device_auth_id") or "").strip()
    interval = max(3, int(payload.get("interval") or 5))
    expires_in = int(payload.get("expires_in") or 15 * 60)
    if not user_code or not device_auth_id:
        raise RuntimeError("OpenAI did not return a usable device auth code")

    state = {
        "provider": "openai-codex",
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "verification_url": f"{ISSUER}/codex/device",
        "poll_interval": interval,
        "expires_at": int(time.time()) + expires_in,
        "created_at": _iso_now(),
    }
    _write_private_json(_pending_path(), state)

    print("ChatGPT/Codex sign-in started.")
    print(f"Open: {state['verification_url']}")
    print(f"Code: {user_code}")
    print("After approval, tell Hermes: I finished ChatGPT sign-in")
    return 0


def _save_codex_tokens(tokens: dict[str, Any]) -> None:
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not access_token:
        raise RuntimeError("OpenAI token exchange did not return an access token")

    auth_store = _read_json(_auth_path()) or {"version": 1, "providers": {}}
    providers = auth_store.setdefault("providers", {})
    providers["openai-codex"] = {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        "last_refresh": _iso_now(),
        "auth_mode": "chatgpt",
        "base_url": os.environ.get("HERMES_CODEX_BASE_URL", "").strip().rstrip("/") or DEFAULT_CODEX_BASE_URL,
    }
    auth_store["version"] = 1
    auth_store["active_provider"] = "openai-codex"
    _write_private_json(_auth_path(), auth_store)


def poll_auth(_args: argparse.Namespace) -> int:
    pending = _read_json(_pending_path())
    if not pending:
        print("No pending ChatGPT/Codex sign-in. Run: python3 scripts/codex_auth_device.py start")
        return 2

    if int(pending.get("expires_at") or 0) <= int(time.time()):
        _pending_path().unlink(missing_ok=True)
        print("The ChatGPT/Codex sign-in code expired. Start again.")
        return 3

    poll = requests.post(
        f"{ISSUER}/api/accounts/deviceauth/token",
        json={
            "device_auth_id": pending["device_auth_id"],
            "user_code": pending["user_code"],
        },
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    if poll.status_code in {403, 404}:
        print("Still waiting for ChatGPT approval. Ask the user to finish the sign-in page, then poll again.")
        return 1
    if poll.status_code >= 400:
        raise RuntimeError(f"OpenAI device auth poll returned HTTP {poll.status_code}")

    code_payload = poll.json()
    authorization_code = str(code_payload.get("authorization_code") or "").strip()
    code_verifier = str(code_payload.get("code_verifier") or "").strip()
    if not authorization_code or not code_verifier:
        raise RuntimeError("OpenAI device auth response was missing authorization details")

    token_payload = _request_json(
        "POST",
        CODEX_OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": f"{ISSUER}/deviceauth/callback",
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    _save_codex_tokens(token_payload)
    _pending_path().unlink(missing_ok=True)
    print("ChatGPT/Codex is connected for this Hermes agent.")
    return 0


def status(_args: argparse.Namespace) -> int:
    auth_store = _read_json(_auth_path())
    provider = (auth_store.get("providers") or {}).get("openai-codex") if auth_store else None
    if provider and (provider.get("tokens") or {}).get("access_token"):
        print("ChatGPT/Codex is connected.")
        return 0
    if _pending_path().exists():
        print("ChatGPT/Codex sign-in is pending.")
        return 1
    print("ChatGPT/Codex is not connected.")
    return 2


def clear_pending(_args: argparse.Namespace) -> int:
    _pending_path().unlink(missing_ok=True)
    print("Cleared pending ChatGPT/Codex sign-in.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Hermes ChatGPT/Codex device auth")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start").set_defaults(func=start_auth)
    subparsers.add_parser("poll").set_defaults(func=poll_auth)
    subparsers.add_parser("status").set_defaults(func=status)
    subparsers.add_parser("clear").set_defaults(func=clear_pending)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
