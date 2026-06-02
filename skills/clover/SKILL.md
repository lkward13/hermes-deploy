---
name: clover
description: Read orders, customers, inventory, payments, and employees from the customer's Clover POS via the Clover REST API. Token-authenticated; no username/password needed.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [Clover, POS, payments, retail, restaurant]
---

# Clover POS

Read merchant data from the customer's Clover Point-of-Sale account: orders, customers, items (inventory), payments, and employees. Authenticates via the API token NoDesk pushes to the agent's `.env` at credential-sync time — there is **no** username/password flow.

## Authentication

This skill reads credentials from `$HOME/.hermes/.env`:

- `CLOVER_ACCESS_TOKEN` — the OAuth access token or a direct API token pasted by the customer in the NoDesk portal. Sent as `Authorization: Bearer <token>`.
- `CLOVER_MERCHANT_ID` — the Clover merchant ID this token is scoped to. Required for every API call. (e.g. `1C2YAXZ6ZHYW1`)
- `CLOVER_SANDBOX` — `"true"` selects the sandbox API host (`apisandbox.dev.clover.com`); anything else uses production (`api.clover.com`). Defaults to production if unset.
- `CLOVER_REFRESH_TOKEN`, `CLOVER_APP_ID`, `CLOVER_APP_SECRET` — present for the OAuth flow; not used by the read-only lookup script. Token refresh is handled by NoDesk's credential sync, not by the agent.

**Do NOT** check for `CLOVER_USERNAME` or `CLOVER_PASSWORD`. Those do not exist. If the lookup returns a 401, the access token is invalid — trigger a fresh credential sync from NoDesk (admin panel → Re-sync) or have the customer re-OAuth Clover.

## Commands

All commands run from the agent's venv. Substitute the actual `HERMES_HOME` if it's not `/home/hermes/.hermes`.

```bash
# Sanity check — print the merchant's name and address
python3 ~/.hermes/skills/clover/clover_lookup.py --merchant-info

# Orders (most recent first by default)
python3 ~/.hermes/skills/clover/clover_lookup.py --list-orders
python3 ~/.hermes/skills/clover/clover_lookup.py --list-orders --limit 20
python3 ~/.hermes/skills/clover/clover_lookup.py --get-order ABC123XYZ

# Customers
python3 ~/.hermes/skills/clover/clover_lookup.py --list-customers --limit 50
python3 ~/.hermes/skills/clover/clover_lookup.py --search-customer "Devin"
python3 ~/.hermes/skills/clover/clover_lookup.py --search-customer "+14059992900"

# Inventory items
python3 ~/.hermes/skills/clover/clover_lookup.py --list-items
python3 ~/.hermes/skills/clover/clover_lookup.py --list-items --limit 200

# Payments
python3 ~/.hermes/skills/clover/clover_lookup.py --list-payments --limit 20

# Employees
python3 ~/.hermes/skills/clover/clover_lookup.py --list-employees

# JSON output (raw, for piping/composition)
python3 ~/.hermes/skills/clover/clover_lookup.py --list-orders --limit 5 --json
```

## What the agent can do with this

- "What sold today?" — `--list-orders --limit 50`, sum amounts, filter by createdTime
- "Who's our top customer?" — `--list-customers`, then `--list-orders` per customer
- "Find a customer's phone" — `--search-customer NAME`
- "What's in inventory?" — `--list-items`
- "Were any payments declined yesterday?" — `--list-payments`, inspect `result` field

The Clover API is read-heavy by default. This skill does not write (no creating orders, refunds, or inventory changes). If a customer asks for write operations, escalate to the NoDesk admin to extend the skill — Clover writes have legal/compliance implications around payment data.

## Sandbox vs production

The connect portal supports both. When `CLOVER_SANDBOX=true`, the merchant is a Clover dev sandbox merchant (no real money). When `false` (production), all data is the live business. The skill auto-routes — there is nothing for the agent to configure.

## Troubleshooting

- **`401 Unauthorized`** — Token expired or revoked. Trigger NoDesk credential sync.
- **`404 Merchant not found`** — `CLOVER_MERCHANT_ID` is wrong or the token isn't scoped to it. Verify in the connect portal.
- **`empty results but the merchant exists`** — Sandbox merchants are empty by default. Add test data in the Clover sandbox dashboard if you need fixtures.
