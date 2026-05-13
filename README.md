# Hermes Deploy

Deployable Hermes runtime bundle for NoDesk client VPSes.

This repo contains:

- Reusable Hermes skills copied from the pilot instance
- Templates for per-client `SOUL.md`, `.env`, `config.yaml`, cron, channels, and webhook subscriptions
- `bootstrap.sh`, which installs Hermes Agent from `NousResearch/hermes-agent`, renders templates, and starts the gateway service

## Bootstrap

Run as root on a fresh Ubuntu VPS:

```bash
export HERMES_DEPLOY_REPO="https://github.com/lkward13/hermes-deploy.git"
export BUSINESS_NAME="Client Business"
export OWNER_NAME="Owner Name"
export OWNER_PHONE="+15555555555"
export ADMIN_NAME="NoDesk Admin"
export ADMIN_PHONE="+15555555555"
export ADMIN_TELEGRAM_ID="7596854319"
export OWNER_TELEGRAM_ID=""
export TELEGRAM_ALLOWED_USERS="7596854319"
export TELEGRAM_OWNER_CHAT_ID="7596854319"
export TELEGRAM_BOT_TOKEN="..."
export CLICKSEND_USERNAME="..."
export CLICKSEND_API_KEY="..."
export CLICKSEND_FROM_NUMBER="+1..."
export FB_PAGE_ACCESS_TOKEN="..."
export FB_FORM_ID="..."
export QBO_CLIENT_ID="..."
export QBO_CLIENT_SECRET="..."

bash bootstrap.sh
```

## Notes

- Secrets must be supplied at bootstrap time or written to `.env` after install.
- `auth.json`, OAuth token files, ClickSend keys, Facebook tokens, and QBO token files are intentionally ignored by git.
- The Hermes agent runtime is installed from `https://github.com/NousResearch/hermes-agent.git` at the pinned commit in `bootstrap.sh`.
