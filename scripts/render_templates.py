#!/usr/bin/env python3
"""Render Hermes deployment templates from environment variables."""

from __future__ import annotations

import os
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

OUTPUTS = {
    "SOUL.md": ROOT / "SOUL.md",
    "config.yaml": ROOT / "config.yaml",
    "webhook_subscriptions.json": ROOT / "webhook_subscriptions.json",
    "channel_directory.json": ROOT / "channel_directory.json",
    "cron_jobs.json": ROOT / "cron" / "jobs.json",
}

SECRET_OUTPUTS = {
    "HERMES_AUTH_JSON": ROOT / "auth.json",
    "QBO_TOKENS_JSON": ROOT / "skills" / "qbo-invoicing" / "qbo_tokens.json",
    "QBO_SECRETS_JSON": ROOT / "skills" / "qbo-invoicing" / "qbo_secrets.json",
    "OAUTH_TOKENS_JSON": ROOT / "credentials" / "oauth_tokens.json",
}

DEFAULTS = {
    "AGENT_PERSONA_NAME": "Hermes",
    "AGENT_SUBAGENT_NAME": "Richard",
    "ADMIN_NAME": "NoDesk Admin",
    "ADMIN_PHONE": "",
    "ADMIN_TELEGRAM_ID": "",
    "BUSINESS_NAME": "Client Business",
    "HERMES_HOME": str(ROOT),
    "HERMES_GATEWAY_TOKEN": "",
    "HERMES_CODEX_BASE_URL": "",
    "OWNER_NAME": "Owner",
    "OWNER_PHONE": "",
    "OWNER_TELEGRAM_ID": "",
    "TELEGRAM_ALLOWED_USERS": "",
    "TELEGRAM_BOT_USERNAME": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_OWNER_CHAT_ID": "",
    "WHATSAPP_ALLOWED_USERS": "",
    "WHATSAPP_ENABLED": "false",
    "WHATSAPP_MODE": "bot",
    "WHATSAPP_PHONE_NUMBER": "",
    "SLACK_ENABLED": "false",
    "SLACK_BOT_TOKEN": "",
    "SLACK_APP_TOKEN": "",
    "SLACK_ALLOWED_USERS": "",
    "SLACK_TEAM_ID": "",
    "BOLDTRAIL_ACCESS_TOKEN": "",
    "BOLDTRAIL_API_TOKEN": "",
    "CLICKSEND_API_KEY": "",
    "CLICKSEND_FROM_NUMBER": "",
    "CLICKSEND_USERNAME": "",
    "FACEBOOK_ACCESS_TOKEN": "",
    "FB_FORM_ID": "",
    "FB_PAGE_ACCESS_TOKEN": "",
    "JOBBER_ACCESS_TOKEN": "",
    "JOBBER_CLIENT_ID": "",
    "JOBBER_CLIENT_SECRET": "",
    "JOBBER_REFRESH_TOKEN": "",
    "QBO_ACCESS_TOKEN": "",
    "QBO_CLIENT_ID": "",
    "QBO_CLIENT_SECRET": "",
    "QBO_REALM_ID": "",
    "QBO_REDIRECT_URI": "",
    "QBO_REFRESH_TOKEN": "",
    "PODIO_APP_ID": "",
    "PODIO_ACCESS_TOKEN": "",
    "PODIO_CLIENT_ID": "",
    "PODIO_CLIENT_SECRET": "",
    "PODIO_REFRESH_TOKEN": "",
    "HERMES_CLIENT_ID": "",
    "NODESK_BASE_URL": "https://nodesk.io",
    "GITHUB_INSTALLATION_ID": "",
    "GITHUB_ACCOUNT_LOGIN": "",
    "GITHUB_TOKEN_ENDPOINT": "",
    "GITHUB_TOKEN": "",
    "GH_TOKEN": "",
    "OPENAI_API_KEY": "",
    "IMAGE_GEN_PROVIDER": "openai-codex",
}


def render(text: str) -> str:
    values = DEFAULTS | os.environ
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def write_secret_json(env_key: str, output_path: Path) -> None:
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return

    data = json.loads(raw)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2) + "\n")
    output_path.chmod(0o600)


def main() -> int:
    for template_name, output_path in OUTPUTS.items():
        template_path = TEMPLATES / template_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render(template_path.read_text()))

    env_template = ROOT / ".env.template"
    env_output = ROOT / ".env"
    env_output.write_text(render(env_template.read_text()))
    env_output.chmod(0o600)

    for env_key, output_path in SECRET_OUTPUTS.items():
        write_secret_json(env_key, output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
