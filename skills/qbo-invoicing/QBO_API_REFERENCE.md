# QuickBooks Online API Reference

> Practical cheat sheet for QBO invoicing workflows. All examples use Python `requests`.

## Base Config

```python
import requests

BASE_URL = "https://quickbooks.api.intuit.com/v3/company/{realm_id}"
SANDBOX_URL = "https://sandbox-quickbooks.api.intuit.com/v3/company/{realm_id}"

HEADERS = {
    "Authorization": "Bearer {access_token}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

MINOR_VERSION = 73  # use latest minor version
```

All endpoints below are relative to `BASE_URL`. Append `?minorversion=73` to every request.

---

## 1. Invoice API

### Create Invoice

```
POST /invoice?minorversion=73
```

**Required fields:** `CustomerRef`, `Line` (at least one line item).

```python
invoice = {
    "CustomerRef": {"value": "123"},
    "AllowOnlineCreditCardPayment": True,
    "AllowOnlineACHPayment": True,
    "BillEmail": {"Address": "customer@example.com"},
    "DueDate": "2026-06-15",
    "Line": [
        {
            "Amount": 500.00,
            "DetailType": "SalesItemLineDetail",
            "Description": "Web development services - May 2026",
            "SalesItemLineDetail": {
                "ItemRef": {"value": "45", "name": "Web Dev"},
                "Qty": 10,
                "UnitPrice": 50.00,
            },
        },
        {
            "Amount": 200.00,
            "DetailType": "SalesItemLineDetail",
            "Description": "Hosting setup",
            "SalesItemLineDetail": {
                "ItemRef": {"value": "46"},
                "Qty": 1,
                "UnitPrice": 200.00,
            },
        },
    ],
}

resp = requests.post(
    f"{BASE_URL}/invoice?minorversion=73",
    headers=HEADERS,
    json=invoice,
)
created = resp.json()["Invoice"]
invoice_id = created["Id"]
sync_token = created["SyncToken"]
```

**Online payment flags:**
- `AllowOnlineCreditCardPayment: true` — shows credit card option on customer-facing invoice
- `AllowOnlineACHPayment: true` — shows ACH/bank transfer option
- Requires `Preferences.SalesFormsPrefs.ETransactionPaymentEnabled = true` in your QBO account

### Read Invoice

```
GET /invoice/{invoiceId}?minorversion=73
```

```python
resp = requests.get(f"{BASE_URL}/invoice/{invoice_id}?minorversion=73", headers=HEADERS)
invoice = resp.json()["Invoice"]
```

### Get Invoice with Payment Link

To get the customer-facing payment URL, add `include=invoiceLink`:

```
GET /invoice/{invoiceId}?minorversion=73&include=invoiceLink
```

```python
resp = requests.get(
    f"{BASE_URL}/invoice/{invoice_id}?minorversion=73&include=invoiceLink",
    headers=HEADERS,
)
data = resp.json()["Invoice"]
payment_url = data.get("InvoiceLink")  # customer-facing "Pay Now" URL
```

### Update Invoice

```
POST /invoice?minorversion=73
```

Must include `Id` and current `SyncToken`. Send the full object (sparse updates supported with `sparse: true`).

```python
update = {
    "Id": invoice_id,
    "SyncToken": sync_token,
    "sparse": True,
    "DueDate": "2026-07-01",
    "CustomerMemo": {"value": "Payment due in 30 days"},
}

resp = requests.post(
    f"{BASE_URL}/invoice?minorversion=73",
    headers=HEADERS,
    json=update,
)
updated = resp.json()["Invoice"]
sync_token = updated["SyncToken"]  # always capture new SyncToken
```

### Send Invoice via Email

```
POST /invoice/{invoiceId}/send?sendTo=customer@example.com
```

```python
resp = requests.post(
    f"{BASE_URL}/invoice/{invoice_id}/send?sendTo=customer@example.com&minorversion=73",
    headers=HEADERS,
    json={},  # empty body, or omit
)
```

Without `sendTo`, uses the `BillEmail` on the invoice object.

### Void Invoice

```
POST /invoice?operation=void&minorversion=73
```

```python
resp = requests.post(
    f"{BASE_URL}/invoice?operation=void&minorversion=73",
    headers=HEADERS,
    json={"Id": invoice_id, "SyncToken": sync_token},
)
```

### Delete Invoice

```
POST /invoice?operation=delete&minorversion=73
```

```python
resp = requests.post(
    f"{BASE_URL}/invoice?operation=delete&minorversion=73",
    headers=HEADERS,
    json={"Id": invoice_id, "SyncToken": sync_token},
)
```

> **Prefer void over delete** — void keeps an audit trail; delete is permanent.

### Query Invoices

```
GET /query?query=SELECT * FROM Invoice WHERE ...&minorversion=73
```

```python
import urllib.parse

# All unpaid invoices
query = "SELECT * FROM Invoice WHERE Balance > '0' ORDERBY DueDate STARTPOSITION 1 MAXRESULTS 100"
resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
invoices = resp.json()["QueryResponse"].get("Invoice", [])

# Invoices for a specific customer
query = "SELECT * FROM Invoice WHERE CustomerRef = '123'"

# Invoices in a date range
query = "SELECT * FROM Invoice WHERE TxnDate >= '2026-01-01' AND TxnDate <= '2026-05-31'"

# Overdue invoices
query = "SELECT * FROM Invoice WHERE DueDate < '2026-05-13' AND Balance > '0'"

# Search by doc number
query = "SELECT * FROM Invoice WHERE DocNumber = '1042'"
```

### Check if Invoice is Paid

```python
resp = requests.get(f"{BASE_URL}/invoice/{invoice_id}?minorversion=73", headers=HEADERS)
invoice = resp.json()["Invoice"]

total = float(invoice["TotalAmt"])
balance = float(invoice["Balance"])

if balance == 0:
    print("PAID IN FULL")
elif balance < total:
    print(f"PARTIALLY PAID — {total - balance:.2f} received, {balance:.2f} remaining")
else:
    print("UNPAID")
```

---

## 2. Customer API

### Create Customer

```
POST /customer?minorversion=73
```

**Only required field:** `DisplayName` (must be unique across all customers/vendors/employees).

```python
customer = {
    "DisplayName": "Acme Corp",
    "CompanyName": "Acme Corporation",
    "GivenName": "John",
    "FamilyName": "Doe",
    "PrimaryEmailAddr": {"Address": "john@acme.com"},
    "PrimaryPhone": {"FreeFormNumber": "(555) 867-5309"},
    "BillAddr": {
        "Line1": "123 Main Street",
        "City": "Austin",
        "CountrySubDivisionCode": "TX",
        "PostalCode": "78701",
        "Country": "US",
    },
}

resp = requests.post(
    f"{BASE_URL}/customer?minorversion=73",
    headers=HEADERS,
    json=customer,
)
cust = resp.json()["Customer"]
customer_id = cust["Id"]
```

### Query/Search Customers

```python
import urllib.parse

# By display name
query = "SELECT * FROM Customer WHERE DisplayName = 'Acme Corp'"

# Partial match (LIKE with % wildcard)
query = "SELECT * FROM Customer WHERE DisplayName LIKE 'Acme%'"

# By email
query = "SELECT * FROM Customer WHERE PrimaryEmailAddr = 'john@acme.com'"

# Active customers only
query = "SELECT * FROM Customer WHERE Active = true STARTPOSITION 1 MAXRESULTS 100"

resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
customers = resp.json()["QueryResponse"].get("Customer", [])
```

### Update Customer

```python
update = {
    "Id": customer_id,
    "SyncToken": cust["SyncToken"],
    "sparse": True,
    "PrimaryEmailAddr": {"Address": "newemail@acme.com"},
}

resp = requests.post(
    f"{BASE_URL}/customer?minorversion=73",
    headers=HEADERS,
    json=update,
)
```

---

## 3. Payment API

### Read Payment

```
GET /payment/{paymentId}?minorversion=73
```

```python
resp = requests.get(f"{BASE_URL}/payment/{payment_id}?minorversion=73", headers=HEADERS)
payment = resp.json()["Payment"]
```

### Query Payments

```python
# All payments for a customer
query = "SELECT * FROM Payment WHERE CustomerRef = '123'"

# Payments in a date range
query = "SELECT * FROM Payment WHERE TxnDate >= '2026-05-01' AND TxnDate <= '2026-05-31'"

# Recent payments
query = "SELECT * FROM Payment ORDERBY TxnDate DESC STARTPOSITION 1 MAXRESULTS 25"

resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
payments = resp.json()["QueryResponse"].get("Payment", [])
```

### Find Payments Linked to an Invoice

Payments reference invoices in their `Line` array:

```python
query = "SELECT * FROM Payment WHERE CustomerRef = '123'"
resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
payments = resp.json()["QueryResponse"].get("Payment", [])

for payment in payments:
    for line in payment.get("Line", []):
        for linked in line.get("LinkedTxn", []):
            if linked["TxnType"] == "Invoice" and linked["TxnId"] == target_invoice_id:
                print(f"Payment {payment['Id']}: ${payment['TotalAmt']} on {payment['TxnDate']}")
```

### Record a Payment Against an Invoice

```python
payment = {
    "CustomerRef": {"value": "123"},
    "TotalAmt": 500.00,
    "Line": [
        {
            "Amount": 500.00,
            "LinkedTxn": [
                {"TxnId": invoice_id, "TxnType": "Invoice"}
            ],
        }
    ],
}

resp = requests.post(
    f"{BASE_URL}/payment?minorversion=73",
    headers=HEADERS,
    json=payment,
)
```

---

## 4. Item/Service API

### Create a Service Item

```
POST /item?minorversion=73
```

```python
item = {
    "Name": "Consulting Services",
    "Type": "Service",
    "Description": "Professional consulting - hourly rate",
    "UnitPrice": 150.00,
    "IncomeAccountRef": {"value": "1", "name": "Services"},
    "Taxable": False,
}

resp = requests.post(
    f"{BASE_URL}/item?minorversion=73",
    headers=HEADERS,
    json=item,
)
item_data = resp.json()["Item"]
item_id = item_data["Id"]
```

**Required fields:** `Name`, `Type`, `IncomeAccountRef`.

For `Type`, use:
- `"Service"` — non-inventory service
- `"Inventory"` — tracked inventory (also needs `ExpenseAccountRef`, `AssetAccountRef`, `QtyOnHand`, `InvStartDate`)
- `"NonInventory"` — physical goods not tracked

### Query Items

```python
# All active service items
query = "SELECT * FROM Item WHERE Type = 'Service' AND Active = true"

# By name
query = "SELECT * FROM Item WHERE Name = 'Consulting Services'"

# Search by partial name
query = "SELECT * FROM Item WHERE Name LIKE 'Consult%'"

resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
items = resp.json()["QueryResponse"].get("Item", [])
```

### Find Your Income Account Ref

You need an `IncomeAccountRef` to create items. Query for it:

```python
query = "SELECT * FROM Account WHERE AccountType = 'Income'"
resp = requests.get(
    f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
    headers=HEADERS,
)
accounts = resp.json()["QueryResponse"].get("Account", [])
for acct in accounts:
    print(f"  Id={acct['Id']}  Name={acct['Name']}")
```

---

## 5. Query Syntax Reference

QBO uses SQL-like queries via the `/query` endpoint.

```
SELECT * FROM EntityName WHERE clause ORDERBY field [ASC|DESC] STARTPOSITION n MAXRESULTS n
```

### Rules & Limitations
- **No projections** — must use `SELECT *`
- **No OR** — only AND in WHERE clauses
- **No JOINs** — query one entity at a time
- **No GROUP BY / aggregation**
- **Wildcards** — only `%` with `LIKE` (e.g., `LIKE 'Acme%'`)
- **String values** — single quotes: `WHERE Name = 'Acme'`
- **Date values** — single quotes, ISO format: `WHERE TxnDate >= '2026-01-01'`
- **Boolean values** — no quotes: `WHERE Active = true`

### Pagination

```python
start = 1
page_size = 100

while True:
    query = f"SELECT * FROM Invoice STARTPOSITION {start} MAXRESULTS {page_size}"
    resp = requests.get(
        f"{BASE_URL}/query?query={urllib.parse.quote(query)}&minorversion=73",
        headers=HEADERS,
    )
    data = resp.json()["QueryResponse"]
    results = data.get("Invoice", [])

    if not results:
        break

    for inv in results:
        process(inv)

    start += page_size
```

---

## 6. Common Patterns

### Authentication

OAuth 2.0 with Bearer token. Token refresh:

```python
def refresh_access_token(client_id, client_secret, refresh_token):
    resp = requests.post(
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        auth=(client_id, client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    data = resp.json()
    return data["access_token"], data["refresh_token"]
```

Access tokens expire in **1 hour**. Refresh tokens expire in **100 days**.

### Error Handling

```python
resp = requests.post(url, headers=HEADERS, json=payload)

if resp.status_code != 200:
    error = resp.json().get("Fault", {})
    for e in error.get("Error", []):
        code = e.get("code")
        msg = e.get("Message")
        detail = e.get("Detail")
        print(f"QBO Error {code}: {msg} — {detail}")
```

**Common error codes:**

| Code | Meaning | Fix |
|------|---------|-----|
| 5010 | Stale object | Re-fetch entity to get current SyncToken, retry |
| 6000 | Business validation | Check required fields, account mappings |
| 6210 | Duplicate doc number | Use unique DocNumber or omit to auto-generate |
| 6240 | Duplicate name | DisplayName already exists (customer/vendor/employee) |
| 610  | Object not found | Entity was deleted or deactivated |
| 2500 | Invalid reference ID | Referenced account/customer/item was deleted |
| 3200 | Authorization failed | Token expired — refresh and retry |
| 429  | Throttled | Rate limit hit — back off and retry |

### Rate Limits

- **500 requests/minute** per realmId (company)
- **10 concurrent requests** per realmId
- Implement exponential backoff on 429 responses

### Request Helper

```python
import time
import urllib.parse

class QBOClient:
    def __init__(self, realm_id, access_token):
        self.base = f"https://quickbooks.api.intuit.com/v3/company/{realm_id}"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.minor_version = 73

    def _url(self, path):
        sep = "&" if "?" in path else "?"
        return f"{self.base}/{path}{sep}minorversion={self.minor_version}"

    def get(self, path):
        resp = requests.get(self._url(path), headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def post(self, path, data):
        resp = requests.post(self._url(path), headers=self.headers, json=data)
        resp.raise_for_status()
        return resp.json()

    def query(self, q):
        return self.get(f"query?query={urllib.parse.quote(q)}")["QueryResponse"]

    def get_invoice(self, invoice_id):
        return self.get(f"invoice/{invoice_id}")["Invoice"]

    def get_invoice_with_link(self, invoice_id):
        return self.get(f"invoice/{invoice_id}?include=invoiceLink")["Invoice"]

    def create_invoice(self, data):
        return self.post("invoice", data)["Invoice"]

    def send_invoice(self, invoice_id, email=None):
        path = f"invoice/{invoice_id}/send"
        if email:
            path += f"?sendTo={email}"
        return self.post(path, {})

    def void_invoice(self, invoice_id, sync_token):
        return self.post(
            "invoice?operation=void",
            {"Id": invoice_id, "SyncToken": sync_token},
        )

    def create_customer(self, data):
        return self.post("customer", data)["Customer"]

    def create_item(self, data):
        return self.post("item", data)["Item"]

    def is_invoice_paid(self, invoice_id):
        inv = self.get_invoice(invoice_id)
        return float(inv["Balance"]) == 0
```

---

## 7. Webhooks

### Setup

1. Go to **Intuit Developer Portal** → your app → **Webhooks** tab
2. Enter your HTTPS endpoint URL (must be publicly accessible, TLS 1.2+)
3. Select entities to subscribe to: `Invoice`, `Payment`, `Customer`
4. Copy the **Verifier Token** — used for signature verification

### Webhook Payload

```json
{
  "eventNotifications": [
    {
      "realmId": "123456789",
      "dataChangeEvent": {
        "entities": [
          {
            "name": "Payment",
            "id": "456",
            "operation": "Create",
            "lastUpdated": "2026-05-13T12:30:00.000Z"
          }
        ]
      }
    }
  ]
}
```

### Event Types

| Entity | Operations |
|--------|-----------|
| Invoice | Create, Update, Delete, Void, Emailed |
| Payment | Create, Update, Delete |
| Customer | Create, Update, Delete, Merge |

### Signature Verification (Python/Flask)

```python
import hashlib
import hmac
import base64
from flask import request

WEBHOOK_VERIFIER_TOKEN = "your-verifier-token"

def verify_webhook(payload_bytes, signature_header):
    computed = base64.b64encode(
        hmac.new(
            WEBHOOK_VERIFIER_TOKEN.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature_header)

@app.route("/webhooks/qbo", methods=["POST"])
def handle_webhook():
    signature = request.headers.get("intuit-signature")
    if not verify_webhook(request.data, signature):
        return "Invalid signature", 401

    data = request.json
    for notification in data.get("eventNotifications", []):
        realm_id = notification["realmId"]
        for entity in notification["dataChangeEvent"]["entities"]:
            name = entity["name"]       # "Payment", "Invoice", etc.
            entity_id = entity["id"]
            operation = entity["operation"]  # "Create", "Update", etc.

            if name == "Payment" and operation == "Create":
                handle_new_payment(realm_id, entity_id)
            elif name == "Invoice" and operation == "Update":
                check_invoice_status(realm_id, entity_id)

    return "OK", 200
```

### Important Webhook Notes

- Webhooks are **best-effort delivery** — implement idempotency
- The payload only contains entity IDs, not full objects — fetch the entity via API after receiving
- QBO may batch multiple events in one webhook call
- Respond with `200 OK` within **5 seconds** or QBO will retry
- Failed deliveries retry with exponential backoff

---

## 8. Full Invoicing Workflow Example

```python
qbo = QBOClient(realm_id="YOUR_REALM", access_token="YOUR_TOKEN")

# 1. Find or create customer
customers = qbo.query("SELECT * FROM Customer WHERE DisplayName = 'Acme Corp'")
if customers.get("Customer"):
    customer = customers["Customer"][0]
else:
    customer = qbo.create_customer({
        "DisplayName": "Acme Corp",
        "PrimaryEmailAddr": {"Address": "billing@acme.com"},
    })

# 2. Find or create service item
items = qbo.query("SELECT * FROM Item WHERE Name = 'Consulting'")
if items.get("Item"):
    item = items["Item"][0]
else:
    accounts = qbo.query("SELECT * FROM Account WHERE AccountType = 'Income'")
    income_acct = accounts["Account"][0]
    item = qbo.create_item({
        "Name": "Consulting",
        "Type": "Service",
        "UnitPrice": 150.00,
        "IncomeAccountRef": {"value": income_acct["Id"]},
    })

# 3. Create invoice
invoice = qbo.create_invoice({
    "CustomerRef": {"value": customer["Id"]},
    "AllowOnlineCreditCardPayment": True,
    "AllowOnlineACHPayment": True,
    "DueDate": "2026-06-15",
    "Line": [
        {
            "Amount": 1500.00,
            "DetailType": "SalesItemLineDetail",
            "Description": "Consulting — May 2026 (10 hrs)",
            "SalesItemLineDetail": {
                "ItemRef": {"value": item["Id"]},
                "Qty": 10,
                "UnitPrice": 150.00,
            },
        },
    ],
})

# 4. Send invoice
qbo.send_invoice(invoice["Id"], email="billing@acme.com")

# 5. Get payment link for the customer
inv_with_link = qbo.get_invoice_with_link(invoice["Id"])
payment_url = inv_with_link.get("InvoiceLink")
print(f"Customer payment URL: {payment_url}")

# 6. Later — check payment status
if qbo.is_invoice_paid(invoice["Id"]):
    print("Invoice paid!")
else:
    inv = qbo.get_invoice(invoice["Id"])
    print(f"Outstanding: ${inv['Balance']}")
```

---

## Quick curl Reference

```bash
# Create invoice
curl -X POST "$QBO_BASE/invoice?minorversion=73" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"CustomerRef":{"value":"123"},"Line":[{"Amount":100,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]}'

# Read invoice with payment link
curl "$QBO_BASE/invoice/130?minorversion=73&include=invoiceLink" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json"

# Send invoice
curl -X POST "$QBO_BASE/invoice/130/send?sendTo=test@example.com&minorversion=73" \
  -H "Authorization: Bearer $TOKEN"

# Query unpaid invoices
curl -G "$QBO_BASE/query" \
  --data-urlencode "query=SELECT * FROM Invoice WHERE Balance > '0'" \
  -d "minorversion=73" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json"

# Create customer
curl -X POST "$QBO_BASE/customer?minorversion=73" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"DisplayName":"New Customer LLC","PrimaryEmailAddr":{"Address":"hello@newcustomer.com"}}'

# Void invoice
curl -X POST "$QBO_BASE/invoice?operation=void&minorversion=73" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"Id":"130","SyncToken":"2"}'
```

Set `QBO_BASE` first:
```bash
export QBO_BASE="https://quickbooks.api.intuit.com/v3/company/YOUR_REALM_ID"
export TOKEN="your-access-token"
```
