#!/usr/bin/env python3
"""Render Hermes deployment templates from environment variables."""

from __future__ import annotations

import os
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

DEFAULTS = {
    "AGENT_PERSONA_NAME": "Hermes",
    "AGENT_SUBAGENT_NAME": "Richard",
    "ADMIN_NAME": "NoDesk Admin",
    "ADMIN_PHONE": "",
    "ADMIN_TELEGRAM_ID": "",
    "BUSINESS_NAME": "Client Business",
    "HERMES_HOME": str(ROOT),
    "HERMES_GATEWAY_TOKEN": "",
    "OWNER_NAME": "Owner",
    "OWNER_PHONE": "",
    "OWNER_TELEGRAM_ID": "",
    "TELEGRAM_ALLOWED_USERS": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_OWNER_CHAT_ID": "",
}


def render(text: str) -> str:
    values = DEFAULTS | os.environ
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def main() -> int:
    for template_name, output_path in OUTPUTS.items():
        template_path = TEMPLATES / template_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render(template_path.read_text()))

    env_template = ROOT / ".env.template"
    env_output = ROOT / ".env"
    env_output.write_text(render(env_template.read_text()))
    env_output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
