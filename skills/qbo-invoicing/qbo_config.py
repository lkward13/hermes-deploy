"""
QBO configuration — loads credentials from environment variables or secrets file.
"""

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Hermes may export QBO_ENVIRONMENT=sandbox in the gateway; .env must win.
    load_dotenv(Path.home() / ".hermes" / ".env", override=True)
except ImportError:
    pass

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(SKILLS_DIR, "qbo_secrets.json")
TOKENS_FILE = os.path.join(SKILLS_DIR, "qbo_tokens.json")

# Sandbox vs Production
ENVIRONMENT = os.environ.get("QBO_ENVIRONMENT", "sandbox")

SANDBOX_BASE_URL = "https://sandbox-quickbooks.api.intuit.com"
PRODUCTION_BASE_URL = "https://quickbooks.api.intuit.com"

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

SCOPES = "com.intuit.quickbooks.accounting"


def _load_secrets():
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE) as f:
            return json.load(f)
    return {}


def get_client_id():
    return os.environ.get("QBO_CLIENT_ID") or _load_secrets().get("client_id", "")


def get_client_secret():
    return os.environ.get("QBO_CLIENT_SECRET") or _load_secrets().get("client_secret", "")


def get_redirect_uri():
    return os.environ.get("QBO_REDIRECT_URI") or _load_secrets().get(
        "redirect_uri",
        "https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl",
    )


def get_base_url():
    if ENVIRONMENT == "production":
        return PRODUCTION_BASE_URL
    return SANDBOX_BASE_URL
