---
name: qbo-invoicing
description: Create, text, and manage QuickBooks Online invoices. Pairs with the podio skill for lead-status tracking.
version: 1.1.0
author: NoDesk
metadata:
  hermes:
    tags: [QBO, invoicing, SMS, payments]
---

# QBO Invoicing

Create, send, inspect, and delete QuickBooks Online invoices and send payment links by SMS through ClickSend. For Podio lead lookup and status updates, use the standalone `podio` skill at `skills/podio/`; this skill only writes Podio status as a follow-up to invoice events (via inline API calls — no Python import of the podio skill).

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

For Podio status updates after invoice creation (`--podio-item-id` flag), the QBO scripts read the same Podio env vars (`PODIO_CLIENT_ID`, `PODIO_CLIENT_SECRET`, `PODIO_ACCESS_TOKEN`, `PODIO_REFRESH_TOKEN`, `PODIO_APP_ID`) — see the `podio` skill for details.

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

Look up Podio leads/jobs — use the `podio` skill (not this one):

```bash
python3 ~/.hermes/skills/podio/podio_lookup.py --search "Customer Name" --json
python3 ~/.hermes/skills/podio/podio_lookup.py --list-recent --limit 20
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
