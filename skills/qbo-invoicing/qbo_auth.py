#!/usr/bin/env python3
"""
QBO OAuth 2.0 helper — handles authorization, token storage, and auto-refresh.

Usage:
    # Generate the authorization URL (user visits in browser):
    python3 qbo_auth.py authorize

    # Exchange the authorization code + realmId for tokens:
    python3 qbo_auth.py callback --code <AUTH_CODE> --realm-id <REALM_ID>

    # Print a valid access token (auto-refreshes if expired):
    python3 qbo_auth.py token

    # Revoke tokens:
    python3 qbo_auth.py revoke

    # Start a temporary callback server to capture the OAuth redirect:
    python3 qbo_auth.py serve --port 8644
"""

import argparse
import base64
import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from qbo_config import (
    AUTH_URL,
    TOKEN_URL,
    REVOKE_URL,
    SCOPES,
    TOKENS_FILE,
    get_client_id,
    get_client_secret,
    get_redirect_uri,
)


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def load_tokens() -> dict:
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return {}


def save_tokens(data: dict):
    with open(TOKENS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(TOKENS_FILE, 0o600)
    _writeback_to_nodesk(data)


def _writeback_to_nodesk(tokens: dict) -> None:
    """Report the (possibly freshly-rotated) QBO token back to NoDesk so central
    stays authoritative.

    QBO rotates the refresh token on every refresh; this file is the agent's
    source of truth, but NoDesk also keeps a copy it seeds onto a (re)provisioned
    box. Without this write-back, central's copy goes stale and a rebuilt box
    would be seeded a dead token (silent QBO disconnect). Best-effort: never
    raises, short timeout — local persistence already succeeded by the time we
    get here. NoDesk only UPDATES an existing connection, authenticated by the
    agent's own client id (same trust as the GitHub token endpoint).
    """
    base = os.environ.get("NODESK_BASE_URL", "").rstrip("/")
    client_id = os.environ.get("HERMES_CLIENT_ID", "")
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not base or not client_id or not access_token or not refresh_token:
        return
    try:
        requests.post(
            f"{base}/api/qbo/token/{client_id}",
            headers={"X-Hermes-Token": client_id, "Content-Type": "application/json"},
            json={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "realm_id": tokens.get("realm_id", ""),
                "expires_in": tokens.get("expires_in"),
                "token_type": tokens.get("token_type", "Bearer"),
            },
            timeout=10,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _basic_auth_header() -> str:
    creds = f"{get_client_id()}:{get_client_secret()}"
    return "Basic " + base64.b64encode(creds.encode()).decode()


def build_authorize_url(state: str = "hermes") -> str:
    params = {
        "client_id": get_client_id(),
        "scope": SCOPES,
        "redirect_uri": get_redirect_uri(),
        "response_type": "code",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, realm_id: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": get_redirect_uri(),
        },
    )
    resp.raise_for_status()
    token_data = resp.json()
    token_data["realm_id"] = realm_id
    token_data["obtained_at"] = int(time.time())
    save_tokens(token_data)
    return token_data


def refresh_access_token() -> dict:
    """Use the refresh token to get a new access token."""
    tokens = load_tokens()
    if not tokens.get("refresh_token"):
        raise RuntimeError("No refresh token found — run 'authorize' first.")

    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": _basic_auth_header(),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
    )
    resp.raise_for_status()
    new_data = resp.json()
    tokens.update(new_data)
    tokens["obtained_at"] = int(time.time())
    save_tokens(tokens)
    return tokens


def get_access_token() -> str:
    """Return a valid access token, refreshing if necessary."""
    tokens = load_tokens()
    if not tokens.get("access_token"):
        raise RuntimeError("No tokens found — run 'authorize' first.")

    expires_in = tokens.get("expires_in", 3600)
    obtained_at = tokens.get("obtained_at", 0)
    # Refresh 5 minutes before expiry
    if time.time() > obtained_at + expires_in - 300:
        tokens = refresh_access_token()

    return tokens["access_token"]


def get_realm_id() -> str:
    tokens = load_tokens()
    realm_id = tokens.get("realm_id")
    if not realm_id:
        raise RuntimeError("No realm_id stored — run 'authorize' and 'callback' first.")
    return realm_id


def revoke_tokens():
    tokens = load_tokens()
    refresh = tokens.get("refresh_token")
    if not refresh:
        print("No refresh token to revoke.")
        return
    resp = requests.post(
        REVOKE_URL,
        headers={
            "Authorization": _basic_auth_header(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={"token": refresh},
    )
    if resp.status_code == 200:
        print("Tokens revoked successfully.")
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
    else:
        print(f"Revoke failed: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Callback server — captures the OAuth redirect locally
# ---------------------------------------------------------------------------

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params and "realmId" in params:
            code = params["code"][0]
            realm_id = params["realmId"][0]
            try:
                token_data = exchange_code(code, realm_id)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>QBO Authorization Successful!</h1>"
                    b"<p>Tokens saved. You can close this tab.</p>"
                )
                print(f"\nTokens obtained and saved to {TOKENS_FILE}")
                print(f"Realm ID: {realm_id}")
                print(f"Access token expires in: {token_data.get('expires_in', '?')}s")
                # Shut down after success
                import threading
                threading.Thread(target=self.server.shutdown).start()
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Error exchanging code: {e}".encode())
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Missing code or realmId. Error: {error}".encode())

    def log_message(self, format, *args):
        pass  # suppress noisy logs


def serve_callback(port: int = 8644):
    server = HTTPServer(("0.0.0.0", port), OAuthCallbackHandler)
    print(f"Listening for QBO OAuth callback on http://0.0.0.0:{port} ...")
    print("Waiting for redirect after user authorizes in browser...\n")
    server.serve_forever()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="QBO OAuth 2.0 helper")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("authorize", help="Print the authorization URL")

    cb = sub.add_parser("callback", help="Exchange auth code for tokens")
    cb.add_argument("--code", required=True)
    cb.add_argument("--realm-id", required=True)

    sub.add_parser("token", help="Print a valid access token")
    sub.add_parser("revoke", help="Revoke stored tokens")

    srv = sub.add_parser("serve", help="Start OAuth callback server")
    srv.add_argument("--port", type=int, default=8644)

    args = parser.parse_args()

    if args.command == "authorize":
        url = build_authorize_url()
        print("\nVisit this URL in your browser to authorize QuickBooks:\n")
        print(url)
        print()

    elif args.command == "callback":
        data = exchange_code(args.code, args.realm_id)
        print("Tokens saved successfully.")
        print(json.dumps(data, indent=2))

    elif args.command == "token":
        token = get_access_token()
        print(token)

    elif args.command == "revoke":
        revoke_tokens()

    elif args.command == "serve":
        serve_callback(args.port)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
