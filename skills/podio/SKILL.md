---
name: podio
description: Look up Podio leads/jobs and update their status. OAuth-authenticated; no username/password needed.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [Podio, CRM, leads]
---

# Podio

Search, list, and update leads/jobs in the customer's Podio workspace. Authenticates via the OAuth tokens NoDesk pushes to the agent's `.env` at credential-sync time — there is **no** username/password flow.

## Authentication

This skill reads credentials from `$HOME/.hermes/.env`:

- `PODIO_CLIENT_ID`
- `PODIO_CLIENT_SECRET`
- `PODIO_ACCESS_TOKEN` — set by NoDesk after the customer completes Podio OAuth on the connect portal; auto-refreshes via `PODIO_REFRESH_TOKEN`
- `PODIO_APP_ID` — the numeric app ID for the leads/jobs app (set per-customer)

**Do NOT** check for `PODIO_USERNAME` or `PODIO_PASSWORD`. Those do not exist in this environment. If `podio_lookup.py` returns a 401, the access token is mid-rotation — the script automatically refreshes via the refresh token and retries. No manual intervention needed.

## Commands

All commands run from the agent's venv. Substitute the actual `HERMES_HOME` if it's not `/home/hermes/.hermes`.

```bash
# Search by name or phone number
python3 ~/.hermes/skills/podio/podio_lookup.py --search "Devin Burchett"
python3 ~/.hermes/skills/podio/podio_lookup.py --search "+14059992900"

# List most-recent leads
python3 ~/.hermes/skills/podio/podio_lookup.py --list-recent
python3 ~/.hermes/skills/podio/podio_lookup.py --list-recent --limit 20

# JSON output (for piping into other tools)
python3 ~/.hermes/skills/podio/podio_lookup.py --search "Devin" --json

# Update the Invoice Status field on a Podio item
python3 ~/.hermes/skills/podio/podio_lookup.py --update-status 3303283090 "Invoice Sent"
```

Valid statuses for `--update-status`: `New Lead`, `Quoted`, `Invoice Sent`, `Invoice Paid`, `Cancelled`.

## How this skill chains

- **QBO invoicing** (`skills/qbo-invoicing/`): pass `--podio-item-id ITEM_ID` to `create_invoice.py` so the lead status flips to "Invoice Sent" after the invoice is created. The QBO skill calls the Podio API inline (not by importing this script) to avoid a circular dependency.
- **Payment checks** (`skills/qbo-invoicing/check_payments.py`): polls QBO for paid invoices and updates matching Podio items to "Invoice Paid".

## Troubleshooting

- **"Auth failed (401): expired_token"** — should never reach the user because the script auto-refreshes. If it does, the refresh token in the `.env` is broken; trigger a fresh credential sync from NoDesk (admin panel → Re-sync, or have the customer re-OAuth Podio).
- **"PODIO_APP_ID is 0"** — the app the customer wants to query isn't configured. Pull it from their `PODIO_APPS_JSON` (the list of all discovered apps) or have them paste an app ID on the connect portal.
