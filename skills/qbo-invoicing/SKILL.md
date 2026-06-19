---
name: qbo-invoicing
description: Run the customer's QuickBooks Online from chat — read any data + financial reports, create/update/void/delete invoices, estimates, sales receipts, credit memos, payments, customers, vendors, bills, expenses, purchase orders, items, accounts, journal entries, deposits & transfers, send documents, and manage attachments.
version: 2.0.0
author: NoDesk
metadata:
  hermes:
    tags: [QBO, QuickBooks, accounting, invoicing, bookkeeping, reports, AR, AP, payments, SMS]
---

# QuickBooks Online

Full QuickBooks Online control for the connected company. Four tools cover
essentially the whole Accounting API, all sharing one OAuth connection:

| Tool | What it does |
|---|---|
| `qbo_lookup.py` | **Read** — query any entity, run any financial report (read-only) |
| `qbo_write.py` | **Write** — create / update / void / delete / deactivate / send, any entity |
| `qbo_files.py` | **Docs** — download transaction PDFs, upload + list attachments |
| `create_invoice.py` | **Rich invoice** — create + email an invoice AND text the pay link via SMS, with Podio status sync |
| `check_payments.py` | **Reconcile** — poll for paid invoices, update Podio (cron-friendly) |

Run everything from the skill dir with the agent venv:

```bash
cd ~/.hermes/skills/qbo-invoicing
# scripts auto-load ~/.hermes/.env; for create_invoice.py activate the venv first:
source ~/.hermes/hermes-agent/venv/bin/activate
```

## Authentication

Credentials come from `~/.hermes/.env` + `qbo_tokens.json` (auto-refreshing OAuth):

- `QBO_ENVIRONMENT` — `production` or `sandbox` (chooses the API host)
- `QBO_CLIENT_ID`, `QBO_CLIENT_SECRET`, tokens via `qbo_auth.py`

If a call returns **401**, the token couldn't refresh — tell the owner to reconnect QuickBooks in the NoDesk portal. **Do NOT** look for a QBO username/password — it's OAuth only. Connectivity check: `python3 qbo_lookup.py company`.

---

# 1. Read — `qbo_lookup.py`

Read-only. Add `--json` to any command for raw JSON.

```bash
python3 qbo_lookup.py company                                  # company info + connectivity check
python3 qbo_lookup.py query "SELECT * FROM Invoice WHERE Balance > '0'"   # universal escape hatch
python3 qbo_lookup.py list <Entity> [--search NAME] [--where "<clause>"] [--limit N]
python3 qbo_lookup.py get <Entity> <Id>                        # full record
python3 qbo_lookup.py report <ReportName> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--customer ID] [--vendor ID] [--param k=v]
```

**Entities** (`list` / `get` / `query FROM`):
`Customer, Invoice, Estimate, SalesReceipt, CreditMemo, RefundReceipt, Payment` (sales/AR) ·
`Vendor, Bill, BillPayment, VendorCredit, PurchaseOrder, Purchase` (purchases/AP — `Purchase` = expenses/checks/cc charges) ·
`Account, Deposit, Transfer, JournalEntry` (banking/GL) ·
`Item, Employee, TimeActivity, Class, Department, TaxCode, TaxRate, Term, PaymentMethod, Budget, Attachable, CompanyInfo, Preferences`.

**Reports** (`report <Name>`):
`ProfitAndLoss, ProfitAndLossDetail, BalanceSheet, CashFlow, TrialBalance, GeneralLedger, TransactionList,
AgedReceivables, AgedReceivableDetail, AgedPayables, AgedPayableDetail,
CustomerBalance(Detail), VendorBalance(Detail), CustomerSales, ItemSales, VendorExpenses,
ClassSales, DepartmentSales, InventoryValuationSummary, AccountListDetail`.

Common reads:
```bash
python3 qbo_lookup.py list Customer --search "Smith"
python3 qbo_lookup.py list Invoice --where "Balance > '0'" --limit 50      # open A/R
python3 qbo_lookup.py list Bill --where "Balance > '0'"                    # unpaid bills (A/P)
python3 qbo_lookup.py list Estimate --where "TxnStatus = 'Pending'"
python3 qbo_lookup.py report ProfitAndLoss --from 2026-01-01 --to 2026-03-31
python3 qbo_lookup.py report BalanceSheet
python3 qbo_lookup.py report AgedReceivables          # who owes us, by age bucket
python3 qbo_lookup.py report CustomerSales --from 2026-01-01   # sales by customer
python3 qbo_lookup.py report ItemSales --from 2026-01-01       # sales by product/service
```

**Query syntax** (QBO SQL): `SELECT * FROM <Entity> [WHERE …] [ORDERBY …] [STARTPOSITION n] [MAXRESULTS m]`. Only `=, <, >, <=, >=, LIKE, IN`; wrap values in single quotes; `LIKE '%term%'` for fuzzy; no `JOIN`, no `OR` across different fields, max 1000 rows/page. Deeper reference: `QBO_API_REFERENCE.md` §5.

---

# 2. Write — `qbo_write.py`

Uniform create/update/delete across every entity. The agent supplies the JSON
body; the tool adds auth, the realm path, and (for update/delete/void) fetches
the current `SyncToken` automatically. Default output is a short result line;
`--json` returns the full object.

```bash
python3 qbo_write.py create <Entity> '<json>'           # POST a new record
python3 qbo_write.py update <Entity> <Id> '<json>'      # sparse update (only the given fields)
python3 qbo_write.py void   <Entity> <Id>               # void a txn (Invoice/Payment/SalesReceipt/…)
python3 qbo_write.py delete <Entity> <Id>               # delete a txn (irreversible)
python3 qbo_write.py deactivate <Entity> <Id>           # name-list entities (Customer/Vendor/Item — no hard delete)
python3 qbo_write.py send <Entity> <Id> [--email addr]  # email an invoice/estimate
```

**Always read first** to get Ids/refs: `qbo_lookup.py list Vendor --search Acme`, `qbo_lookup.py get Item 1`.

### Body recipes (the common ones)

**Customer / Vendor** (name-list — minimal):
```bash
python3 qbo_write.py create Customer '{"DisplayName":"Jane Doe","PrimaryEmailAddr":{"Address":"jane@x.com"},"PrimaryPhone":{"FreeFormNumber":"+14055551234"}}'
python3 qbo_write.py create Vendor   '{"DisplayName":"Acme Supply","PrimaryEmailAddr":{"Address":"ap@acme.com"}}'
```

**Estimate / Invoice / SalesReceipt / CreditMemo** (sales txn — `CustomerRef` + `Line[]`):
```bash
python3 qbo_write.py create Estimate '{"CustomerRef":{"value":"58"},"Line":[{"Amount":1200,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"},"Qty":1,"UnitPrice":1200}}]}'
# (for a simple service line you can omit ItemRef and use a description-only line — see QBO_API_REFERENCE.md §1)
```

**Bill / Expense (Purchase) / PurchaseOrder** (purchase txn — `VendorRef` + `AccountBasedExpenseLineDetail`):
```bash
python3 qbo_write.py create Bill '{"VendorRef":{"value":"56"},"Line":[{"Amount":300,"DetailType":"AccountBasedExpenseLineDetail","AccountBasedExpenseLineDetail":{"AccountRef":{"value":"7"}}}]}'
python3 qbo_write.py create Purchase '{"PaymentType":"Cash","AccountRef":{"value":"35"},"Line":[{"Amount":42.50,"DetailType":"AccountBasedExpenseLineDetail","AccountBasedExpenseLineDetail":{"AccountRef":{"value":"7"}}}]}'
```

**Payment received** (apply a customer payment to invoices):
```bash
python3 qbo_write.py create Payment '{"CustomerRef":{"value":"58"},"TotalAmt":1200,"Line":[{"Amount":1200,"LinkedTxn":[{"TxnId":"145","TxnType":"Invoice"}]}]}'
```

**JournalEntry / Deposit / Transfer / Item / Account** — same pattern: build the JSON body (shapes in `QBO_API_REFERENCE.md`) and `create`.

**Update** (sparse — only send what changes):
```bash
python3 qbo_write.py update Invoice 145 '{"CustomerMemo":{"value":"Thanks!"},"DueDate":"2026-07-15"}'
python3 qbo_write.py update Customer 58 '{"PrimaryPhone":{"FreeFormNumber":"+14055559999"}}'
```

**Void / delete / deactivate / send:**
```bash
python3 qbo_write.py void Invoice 145          # keeps the record, zeroes it
python3 qbo_write.py delete Estimate 200       # transaction only; irreversible
python3 qbo_write.py deactivate Item 12        # name-list entities can't be hard-deleted
python3 qbo_write.py send Invoice 145 --email customer@example.com
```

> **Destructive ops** (`void`, `delete`) are irreversible in QBO. Confirm with the owner before running — the agent's approval gate will prompt.

---

# 3. PDFs + attachments — `qbo_files.py`

```bash
python3 qbo_files.py pdf Invoice 145                          # -> ./Invoice-145.pdf
python3 qbo_files.py pdf Estimate 88 --out /tmp/quote.pdf
python3 qbo_files.py attach Invoice 145 /path/to/receipt.jpg --note "Signed delivery slip"
python3 qbo_files.py attachments Invoice 145                  # list files on a txn
```

PDF works for Invoice, Estimate, SalesReceipt, CreditMemo, RefundReceipt, Payment, PurchaseOrder. Attach uploads any file and links it to the transaction via the Attachable API.

---

# 4. Rich invoice + SMS — `create_invoice.py`

Use this (not `qbo_write.py create Invoice`) when you want the **full invoice flow**: create + email the invoice AND text the customer the QBO pay link via ClickSend, optionally syncing Podio lead status. Requires the venv active.

```bash
python3 create_invoice.py --customer "Customer Name" --email "c@x.com" --phone "+14055551234" \
  --item "Roof repair" --amount 1234.56 --due-days 30 --sms [--podio-item-id 123456789]
python3 create_invoice.py --status --invoice-id 145
python3 create_invoice.py --list-recent
# --no-send (don't email), --sms-dry-run (preview the text)
```

# 5. Reconciliation — `check_payments.py`

```bash
python3 check_payments.py                 # find newly-paid invoices, update Podio
python3 check_payments.py --dry-run
python3 check_payments.py --invoice-id 145
# cron: */15 * * * *  ... check_payments.py --quiet
```

---

## Common workflows

**"Invoice Jane $1,200 for the roof job and text her the link"** → `create_invoice.py --customer "Jane Doe" --email … --phone … --item "Roof repair" --amount 1200 --sms`.

**"How's the business doing this quarter?"** → `report ProfitAndLoss --from … --to …`, `report BalanceSheet`, `report AgedReceivables`.

**"Who owes us money?"** → `report AgedReceivables` (or `list Invoice --where "Balance > '0'"`).

**"Enter this vendor bill"** → `list Vendor --search …` for the VendorRef, `list Account` for the expense AccountRef, then `create Bill '…'`.

**"Send a quote for $4,500"** → `list Customer --search …`, `create Estimate '…'`, `send Estimate <id> --email …`, optionally `pdf Estimate <id>`.

## Troubleshooting

- **401** — token refresh failed → reconnect QuickBooks in the NoDesk portal.
- **400 with a Fault message** — QBO rejected the body (missing required ref, bad field). The error prints QBO's own message; read it, fix the JSON (check refs exist via `qbo_lookup.py get`), retry.
- **"Object Not Found" / 404** — wrong Id or it's in the other environment (sandbox vs production — check `QBO_ENVIRONMENT`).
- **Stale Object / SyncToken** — `qbo_write.py` re-fetches SyncToken each call, so this is rare; if it happens, just retry.
- **429** — rate limited; wait and retry.
- Deep API detail (exact body shapes, query rules, webhooks): `QBO_API_REFERENCE.md`.
