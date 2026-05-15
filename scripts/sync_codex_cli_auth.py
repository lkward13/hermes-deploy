#!/usr/bin/env python3
"""Translate ~/.hermes/auth.json → ~/.codex/auth.json.

The Hermes Codex device flow captures only access_token + refresh_token. The
standalone `codex` CLI needs a full OIDC bundle (id_token, account_id) in its
own auth file format. This script mints a fresh bundle by refreshing against
auth.openai.com, parses chatgpt_account_id out of the id_token JWT, and writes
the proper ~/.codex/auth.json. After this runs once, `codex` is logged in.

Idempotent. Safe to run repeatedly — codex auto-refreshes its own token
afterward, but re-running on credential sync keeps things tidy.
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))


def main() -> int:
    hermes_auth_path = HERMES_HOME / "auth.json"
    if not hermes_auth_path.exists():
        print(f"sync_codex_cli_auth: {hermes_auth_path} not found — Codex not connected yet")
        return 0  # not an error — nothing to do

    try:
        hermes_auth = json.loads(hermes_auth_path.read_text())
        provider = hermes_auth.get("providers", {}).get("openai-codex", {})
        refresh_token = provider.get("tokens", {}).get("refresh_token", "")
    except Exception as exc:
        print(f"sync_codex_cli_auth: could not read Hermes auth.json: {exc}", file=sys.stderr)
        return 1

    if not refresh_token:
        print("sync_codex_cli_auth: no refresh_token in Hermes auth.json — nothing to do")
        return 0

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CODEX_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        "https://auth.openai.com/oauth/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except Exception as exc:
        print(f"sync_codex_cli_auth: refresh failed: {exc}", file=sys.stderr)
        return 1

    if "id_token" not in tokens:
        print("sync_codex_cli_auth: refresh response missing id_token", file=sys.stderr)
        return 1

    # account_id is encoded in the id_token JWT
    parts = tokens["id_token"].split(".")
    if len(parts) < 2:
        print("sync_codex_cli_auth: id_token is not a JWT", file=sys.stderr)
        return 1
    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as exc:
        print(f"sync_codex_cli_auth: could not parse id_token claims: {exc}", file=sys.stderr)
        return 1
    account_id = (
        claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id")
        or claims.get("account_id")
        or ""
    )

    codex_auth = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": tokens["id_token"],
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", refresh_token),
            "account_id": account_id,
        },
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    out_path = CODEX_HOME / "auth.json"
    out_path.write_text(json.dumps(codex_auth, indent=2))
    os.chmod(out_path, 0o600)
    print(f"sync_codex_cli_auth: wrote {out_path} (account_id={account_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
