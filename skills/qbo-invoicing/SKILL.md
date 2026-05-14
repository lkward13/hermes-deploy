---
name: qbo-invoicing
description: Create, text, and manage QuickBooks Online invoices with optional Podio lookup/status tracking.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [QBO, invoicing, Podio, SMS, payments]
---

# QBO Invoicing

Create, send, inspect, and delete QuickBooks Online invoices. Optionally look up jobs/leads in Podio, update invoice status, and send payment links by SMS through ClickSend.

## Environment

This skill reads credentials from `$HOME/.hermes/.env`.

Required for QBO:

- `QBO_ENVIRONMENT`
- `QBO_CLIENT_ID`
- `QBO_CLIENT_SECRET`
- QBO tokens generated through `qbo_auth.py`

Required for SMS:

- `CLICKSEND_USERNAME`
- `CLICKSEND_API_KEY`
- `CLICKSEND_FROM`

Required for Podio:

- `PODIO_ACCESS_TOKEN` — set automatically by NoDesk credential sync (OAuth)
- `PODIO_REFRESH_TOKEN` + `PODIO_CLIENT_ID` + `PODIO_CLIENT_SECRET` — used to refresh if access token is expired
- `PODIO_APPS_JSON` — JSON array of `{"app_id": "..."}` objects, set automatically by NoDesk
- Legacy fallback: `PODIO_USERNAME` + `PODIO_PASSWORD` (only if OAuth tokens are absent)

Podio lookup works across all apps in `PODIO_APPS_JSON` without any manual configuration.

## Create Invoice

```bash
source ~/.hermes/hermes-agent/venv/bin/activate
cd ~/.hermes/skills/qbo-invoicing

python3 create_invoice.py \
  --customer "CUSTOMER NAME" \
  --email "customer@email.com" \
  --phone "+1XXXXXXXXXX" \
  --item "Description of work" \
  --amount 1234.56 \
  --due-days 30 \
  --sms
```

Use `--no-send` for sandbox/testing when you do not want QBO email delivery.

## Podio Tracking

If invoicing from a Podio lead/job, use `--podio-item-id ITEM_ID` so the Podio status is updated after invoice creation:

```bash
python3 create_invoice.py \
  --customer "Customer Name" \
  --email "customer@example.com" \
  --phone "+1XXXXXXXXXX" \
  --item "Service" \
  --amount 500 \
  --sms \
  --podio-item-id 123456789
```

Look up Podio leads/jobs:

```bash
python3 podio_lookup.py --search "Customer Name" --json
python3 podio_lookup.py --list-recent --limit 20
```

## Payment Checks

Poll QBO for paid invoices and update Podio where possible:

```bash
python3 check_payments.py
python3 check_payments.py --dry-run
python3 check_payments.py --invoice-id 1234
```

Recommended cron:

```cron
*/15 * * * * cd ~/.hermes/skills/qbo-invoicing && ~/.hermes/hermes-agent/venv/bin/python3 check_payments.py --quiet >> /var/log/hermes-payment-check.log 2>&1
```

## Delete Test Invoice

Only hard-delete test invoices or invoices the user explicitly asks to remove. Read the invoice first, capture `Id` and `SyncToken`, then delete using QBO's `operation=delete` endpoint.
