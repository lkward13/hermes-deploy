---
name: clover
description: Read and write orders, customers, inventory, payments, discounts, and tax rates in the customer's Clover POS via the Clover REST API. Requires an Admin-level API token for write operations.
version: 2.0.0
author: NoDesk
metadata:
  hermes:
    tags: [Clover, POS, payments, invoicing, retail, service-business]
---

# Clover POS

Read and write data in the customer's Clover Point-of-Sale account. Authenticates via the API token NoDesk pushes to the agent's `.env` at credential-sync time.

**Write operations require an Admin API token.** If write calls return 403, the customer needs to re-paste their token using an Admin account in their Clover dashboard.

## Authentication

Credentials live in `$HOME/.hermes/.env`:

- `CLOVER_ACCESS_TOKEN` — Bearer token. Must be from an **Admin** employee account for write access.
- `CLOVER_MERCHANT_ID` — 13-char alphanumeric ID from the dashboard URL (e.g. `YG8M20CF2R1D1`). Not the numeric payment MID on statements.
- `CLOVER_SANDBOX` — `"true"` routes to sandbox; anything else uses production.

**Do NOT** look for `CLOVER_USERNAME` or `CLOVER_PASSWORD` — they don't exist.

## Commands

All commands run from the agent's venv. Add `--json` to any command for raw JSON output.

### Read

```bash
# Merchant
python3 ~/.hermes/skills/clover/clover_lookup.py --merchant-info

# Orders
python3 ~/.hermes/skills/clover/clover_lookup.py --list-orders [--limit 20]
python3 ~/.hermes/skills/clover/clover_lookup.py --get-order ORDER_ID

# Customers
python3 ~/.hermes/skills/clover/clover_lookup.py --list-customers [--limit 50]
python3 ~/.hermes/skills/clover/clover_lookup.py --search-customer "Devin"
python3 ~/.hermes/skills/clover/clover_lookup.py --customer-history CUSTOMER_ID

# Revenue reporting
python3 ~/.hermes/skills/clover/clover_lookup.py --sales-summary [--from 2024-01-01] [--to 2024-01-31]
python3 ~/.hermes/skills/clover/clover_lookup.py --top-services [--limit 10] [--from 2024-01-01]

# Inventory, payments, employees
python3 ~/.hermes/skills/clover/clover_lookup.py --list-items [--limit 200]
python3 ~/.hermes/skills/clover/clover_lookup.py --list-payments [--limit 20]
python3 ~/.hermes/skills/clover/clover_lookup.py --list-employees
python3 ~/.hermes/skills/clover/clover_lookup.py --list-discounts
python3 ~/.hermes/skills/clover/clover_lookup.py --list-tax-rates
```

### Write (Admin token required)

```bash
# Customers
python3 ~/.hermes/skills/clover/clover_lookup.py --create-customer --first-name John --last-name Doe [--email j@x.com] [--phone 5551234567]
python3 ~/.hermes/skills/clover/clover_lookup.py --update-customer CUSTOMER_ID [--first-name X] [--last-name X] [--email X] [--phone X]

# Orders / invoicing
python3 ~/.hermes/skills/clover/clover_lookup.py --create-order --service "Full Detail:250.00" [--service "Wax:50.00"] [--customer-id ID] [--note "2022 Honda Civic, silver"]
python3 ~/.hermes/skills/clover/clover_lookup.py --add-line-item --order-id ID --name "Ceramic Coating" --price 300.00
python3 ~/.hermes/skills/clover/clover_lookup.py --attach-customer --order-id ID --customer-id ID
python3 ~/.hermes/skills/clover/clover_lookup.py --add-order-note --order-id ID --note "No wheel wells"
python3 ~/.hermes/skills/clover/clover_lookup.py --delete-order ORDER_ID

# Inventory
python3 ~/.hermes/skills/clover/clover_lookup.py --create-item --name "Full Detail" --price 250.00 [--sku SKU]
python3 ~/.hermes/skills/clover/clover_lookup.py --update-item ITEM_ID [--name X] [--price 275.00]

# Payments
python3 ~/.hermes/skills/clover/clover_lookup.py --refund --payment-id ID [--amount 50.00]  # omit --amount for full refund

# Discounts & tax
python3 ~/.hermes/skills/clover/clover_lookup.py --apply-discount --order-id ID --percent 10 [--name "Loyal Customer"]
python3 ~/.hermes/skills/clover/clover_lookup.py --create-tax-rate --name "Sales Tax" --rate 8.5
```

## Common workflows

**Create a full invoice for a returning customer:**
```bash
# 1. Find the customer
python3 ~/.hermes/skills/clover/clover_lookup.py --search-customer "John Smith"
# 2. Create order with services attached to customer in one shot
python3 ~/.hermes/skills/clover/clover_lookup.py --create-order \
  --service "Full Detail:250.00" \
  --service "Ceramic Coating:300.00" \
  --customer-id CUSTOMER_ID \
  --note "2022 Honda Civic, silver, no wheel wells"
```

**Weekly revenue check:**
```bash
python3 ~/.hermes/skills/clover/clover_lookup.py --sales-summary --from 2024-01-01 --to 2024-01-07
python3 ~/.hermes/skills/clover/clover_lookup.py --top-services --limit 5 --from 2024-01-01
```

**Process a refund:**
```bash
python3 ~/.hermes/skills/clover/clover_lookup.py --get-order ORDER_ID  # find payment ID
python3 ~/.hermes/skills/clover/clover_lookup.py --refund --payment-id PAYMENT_ID  # full refund
python3 ~/.hermes/skills/clover/clover_lookup.py --refund --payment-id PAYMENT_ID --amount 50.00  # partial
```

## Troubleshooting

- **401** — Token expired or invalid. Trigger NoDesk credential sync.
- **403** — Token lacks write permissions. Customer must re-paste token generated from an Admin account.
- **404** — Wrong ID or resource doesn't exist. Double-check merchant ID (URL form, not payment MID).
- **Empty results on sandbox** — Sandbox merchants have no data by default; add fixtures in the Clover developer dashboard.
