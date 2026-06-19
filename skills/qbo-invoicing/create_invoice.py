#!/usr/bin/env python3
"""
Create and send QBO invoices from the command line.

Usage:
    python3 create_invoice.py \
        --customer "Devin Burchett" \
        --email "devin@example.com" \
        --item "Hydroseeding - 5000 sqft backyard" \
        --amount 1500.00 \
        --due-days 30

    # Multiple line items:
    python3 create_invoice.py \
        --customer "Devin Burchett" \
        --email "devin@example.com" \
        --item "Hydroseeding - 5000 sqft backyard" --amount 1500.00 \
        --item "Soil amendment" --amount 250.00 \
        --due-days 30

    # Create invoice and text payment link to customer:
    python3 create_invoice.py \
        --customer "Devin Burchett" \
        --email "devin@example.com" \
        --phone "+14059992900" \
        --item "Hydroseeding - 5000 sqft backyard" \
        --amount 1500.00 \
        --sms

    # Auto-update Podio lead status to "Invoice Sent":
    python3 create_invoice.py \
        --customer "Devin Burchett" \
        --email "devin@example.com" \
        --phone "+14059992900" \
        --item "Hydroseeding" --amount 1500.00 \
        --sms --podio-item-id 3303283090

    # Check invoice status by ID:
    python3 create_invoice.py --status --invoice-id 1234

    # List recent invoices:
    python3 create_invoice.py --list-recent
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta

import requests

from qbo_config import get_base_url
from qbo_auth import get_access_token, get_realm_id


# ---------------------------------------------------------------------------
# ClickSend SMS config
# ---------------------------------------------------------------------------

CLICKSEND_USERNAME = os.environ.get("CLICKSEND_USERNAME", "")
CLICKSEND_API_KEY = os.environ.get("CLICKSEND_API_KEY", "")
CLICKSEND_FROM = os.environ.get("CLICKSEND_FROM", "")
CLICKSEND_API_URL = "https://rest.clicksend.com/v3/sms/send"


# ---------------------------------------------------------------------------
# Podio status update (inline — avoids circular import with podio_lookup)
# ---------------------------------------------------------------------------

PODIO_API = "https://api.podio.com"
PODIO_INVOICE_STATUS_FIELD_ID = 276921460
PODIO_STATUS_OPTIONS = {
    "New Lead": 1,
    "Quoted": 2,
    "Invoice Sent": 3,
    "Invoice Paid": 4,
    "Cancelled": 5,
}

_podio_token_cache = {"access_token": None, "expires_at": 0}


def _load_hermes_env():
    from pathlib import Path
    import time as _time
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip().strip('"')
            os.environ.setdefault(key.strip(), value)


def _refresh_podio_token() -> str:
    import time as _time
    from pathlib import Path as _Path
    import re as _re
    _load_hermes_env()
    refresh_token = os.environ.get("PODIO_REFRESH_TOKEN", "")
    client_id = os.environ.get("PODIO_CLIENT_ID", "")
    client_secret = os.environ.get("PODIO_CLIENT_SECRET", "")
    if not (refresh_token and client_id and client_secret):
        return ""
    resp = requests.post(
        "https://podio.com/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return ""
    data = resp.json()
    new_token = data.get("access_token", "")
    if new_token:
        env_path = _Path.home() / ".hermes" / ".env"
        if env_path.exists():
            content = env_path.read_text()
            content = _re.sub(
                r"^(PODIO_ACCESS_TOKEN=).*$",
                f"PODIO_ACCESS_TOKEN='{new_token}'",
                content, flags=_re.MULTILINE,
            )
            env_path.write_text(content)
        os.environ["PODIO_ACCESS_TOKEN"] = new_token
        _podio_token_cache["access_token"] = new_token
        _podio_token_cache["expires_at"] = _time.time() + data.get("expires_in", 28800)
    return new_token


def _get_podio_token() -> str:
    import time as _time
    now = _time.time()
    if _podio_token_cache["access_token"] and _podio_token_cache["expires_at"] - now > 60:
        return _podio_token_cache["access_token"]

    _load_hermes_env()
    oauth_token = os.environ.get("PODIO_ACCESS_TOKEN", "")
    if oauth_token:
        _podio_token_cache["access_token"] = oauth_token
        _podio_token_cache["expires_at"] = now + 28800
        return oauth_token

    return _refresh_podio_token() or ""


def update_podio_status(item_id: int, status_text: str) -> bool:
    """Set the Invoice Status on a Podio item after invoice creation."""
    if status_text not in PODIO_STATUS_OPTIONS:
        print(f"Warning: Unknown Podio status '{status_text}', skipping update.", file=sys.stderr)
        return False

    token = _get_podio_token()
    if not token:
        print("Warning: Could not authenticate with Podio. Status not updated.", file=sys.stderr)
        return False

    option_id = PODIO_STATUS_OPTIONS[status_text]
    resp = requests.put(
        f"{PODIO_API}/item/{item_id}/value/{PODIO_INVOICE_STATUS_FIELD_ID}",
        headers={
            "Authorization": f"OAuth2 {token}",
            "Content-Type": "application/json",
        },
        json=option_id,
        timeout=15,
    )
    if resp.status_code in (200, 204):
        print(f"Podio item {item_id} -> Invoice Status: {status_text}")
        return True
    else:
        print(f"Warning: Podio status update failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _headers():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _minor_version() -> str:
    """QBO v3 requires minorversion on requests for stable behavior."""
    return os.environ.get("QBO_MINOR_VERSION", "73")


def _merge_params(params: dict | None = None) -> dict:
    merged = {"minorversion": _minor_version()}
    if params:
        merged.update(params)
    return merged


def _api_url(endpoint: str) -> str:
    realm_id = get_realm_id()
    base = get_base_url()
    return f"{base}/v3/company/{realm_id}/{endpoint}"


def _api_get(endpoint: str, params: dict = None) -> dict:
    resp = requests.get(
        _api_url(endpoint),
        headers=_headers(),
        params=_merge_params(params),
    )
    resp.raise_for_status()
    return resp.json()


def _api_post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(
        _api_url(endpoint),
        headers=_headers(),
        params=_merge_params(None),
        json=payload,
    )
    if resp.status_code >= 400:
        print(f"API Error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()


def _query(sql: str) -> list:
    resp = requests.get(
        _api_url("query"),
        headers=_headers(),
        params=_merge_params({"query": sql}),
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("QueryResponse", {})


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------

def find_customer(display_name: str) -> dict | None:
    escaped = display_name.replace("'", "\\'")
    result = _query(f"SELECT * FROM Customer WHERE DisplayName = '{escaped}'")
    customers = result.get("Customer", [])
    return customers[0] if customers else None


def create_customer(display_name: str, email: str = None) -> dict:
    payload = {"DisplayName": display_name}
    if email:
        payload["PrimaryEmailAddr"] = {"Address": email}
    resp = _api_post("customer", payload)
    return resp["Customer"]


def find_or_create_customer(display_name: str, email: str = None) -> dict:
    existing = find_customer(display_name)
    if existing:
        print(f"Found existing customer: {display_name} (ID: {existing['Id']})")
        if email and existing.get("PrimaryEmailAddr", {}).get("Address") != email:
            existing["PrimaryEmailAddr"] = {"Address": email}
            updated = _api_post("customer", existing)
            return updated["Customer"]
        return existing
    print(f"Creating new customer: {display_name}")
    return create_customer(display_name, email)


# ---------------------------------------------------------------------------
# Invoice creation
# ---------------------------------------------------------------------------

def get_invoice_with_link(invoice_id: str) -> dict:
    """
    Re-read an invoice from QBO to get the full object including InvoiceLink.
    The POST response doesn't always include it, but a GET does.
    """
    return _api_get(f"invoice/{invoice_id}")["Invoice"]


def create_invoice(
    customer_id: str,
    line_items: list[dict],
    due_date: str,
    customer_email: str = None,
    send_email: bool = True,
    memo: str = None,
) -> dict:
    """
    Create an invoice in QBO.

    line_items: [{"description": str, "amount": float, "quantity": float}]
    due_date: "YYYY-MM-DD"
    """
    lines = []
    for i, item in enumerate(line_items, 1):
        lines.append({
            "LineNum": i,
            "Amount": item["amount"] * item.get("quantity", 1),
            "DetailType": "SalesItemLineDetail",
            "Description": item["description"],
            "SalesItemLineDetail": {
                "UnitPrice": item["amount"],
                "Qty": item.get("quantity", 1),
            },
        })

    invoice_data = {
        "CustomerRef": {"value": customer_id},
        "DueDate": due_date,
        "Line": lines,
        "AllowOnlineACHPayment": True,
        "AllowOnlineCreditCardPayment": True,
    }

    if customer_email:
        invoice_data["BillEmail"] = {"Address": customer_email}

    if memo:
        invoice_data["CustomerMemo"] = {"value": memo}

    result = _api_post("invoice", invoice_data)
    invoice = result["Invoice"]
    print(f"Invoice created: #{invoice.get('DocNumber', 'N/A')} (ID: {invoice['Id']})")

    invoice = get_invoice_with_link(invoice["Id"])
    payment_link = invoice.get("InvoiceLink")
    if payment_link:
        print(f"Payment link: {payment_link}")
    else:
        print("Payment link: not available (may appear after sending)")

    if send_email and customer_email:
        send_invoice(invoice["Id"])
        invoice = get_invoice_with_link(invoice["Id"])
        if not payment_link and invoice.get("InvoiceLink"):
            print(f"Payment link (post-send): {invoice['InvoiceLink']}")

    return invoice


def send_invoice(invoice_id: str, email: str = None) -> dict:
    """Send an invoice via email."""
    url = _api_url(f"invoice/{invoice_id}/send")
    params: dict = {}
    if email:
        params["sendTo"] = email
    params = _merge_params(params)
    # Empty body with Content-Type: application/json often yields QBO HTTP 500; send explicit {}.
    resp = requests.post(url, headers=_headers(), params=params, json={})
    if resp.status_code >= 400:
        print(f"Invoice send error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    print(f"Invoice {invoice_id} sent via email.")
    if resp.text and resp.text.strip():
        return resp.json()
    return {}


# ---------------------------------------------------------------------------
# SMS helpers
# ---------------------------------------------------------------------------

def send_payment_sms(to: str, customer_name: str, payment_link: str, dry_run: bool = False) -> dict | None:
    """Text the payment link to the customer via ClickSend."""
    first_name = customer_name.split()[0] if customer_name else "there"
    business_name = os.environ.get("BUSINESS_NAME", "the business")
    owner_name = os.environ.get("OWNER_NAME", "the team")
    body = (
        f"Hi {first_name}! Here's your invoice from {business_name}: "
        f"{payment_link}\n"
        f"You can pay online via credit card or bank transfer. Thanks! - {owner_name}"
    )

    if dry_run:
        print(f"[DRY RUN] Would send SMS to {to}:")
        print(f"  {body}")
        return None

    auth_string = base64.b64encode(f"{CLICKSEND_USERNAME}:{CLICKSEND_API_KEY}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
    }
    payload = {
        "messages": [
            {
                "from": CLICKSEND_FROM,
                "to": to,
                "body": body,
                "source": "hermes-qbo-invoicing",
            }
        ]
    }
    resp = requests.post(CLICKSEND_API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    messages = result.get("data", {}).get("messages", [])
    for msg in messages:
        status = msg.get("status", "unknown")
        print(f"SMS sent: {status} | To: {to}")

    return result


# ---------------------------------------------------------------------------
# Invoice queries
# ---------------------------------------------------------------------------

def get_invoice(invoice_id: str) -> dict:
    return _api_get(f"invoice/{invoice_id}")["Invoice"]


def list_recent_invoices(limit: int = 10) -> list:
    result = _query(
        f"SELECT * FROM Invoice ORDER BY MetaData.CreateTime DESC MAXRESULTS {limit}"
    )
    return result.get("Invoice", [])


def print_invoice_summary(inv: dict):
    balance = inv.get("Balance", 0)
    total = inv.get("TotalAmt", 0)
    if balance == 0 and total > 0:
        status = "PAID"
    elif inv.get("DueDate"):
        due = datetime.strptime(inv["DueDate"], "%Y-%m-%d")
        status = "OVERDUE" if due < datetime.now() and balance > 0 else "OPEN"
    else:
        status = "OPEN"

    link = inv.get("InvoiceLink", "")
    link_str = f"  Link: {link}" if link else ""

    print(
        f"  #{inv.get('DocNumber', 'N/A'):>6}  "
        f"ID:{inv['Id']:>5}  "
        f"${total:>10,.2f}  "
        f"Bal: ${balance:>10,.2f}  "
        f"Due: {inv.get('DueDate', 'N/A'):>12}  "
        f"[{status}]  "
        f"{inv.get('CustomerRef', {}).get('name', 'Unknown')}"
        f"{link_str}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Create and send QBO invoices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--customer", help="Customer display name")
    parser.add_argument("--email", help="Customer email for sending invoice")
    parser.add_argument("--phone", help="Customer phone number (E.164 format, for --sms)")
    parser.add_argument(
        "--item", action="append", dest="items",
        help="Line item description (pair with --amount)",
    )
    parser.add_argument(
        "--amount", action="append", dest="amounts", type=float,
        help="Line item amount (pair with --item)",
    )
    parser.add_argument(
        "--quantity", action="append", dest="quantities", type=float,
        help="Line item quantity (defaults to 1)",
    )
    parser.add_argument("--due-days", type=int, default=30, help="Days until due (default 30)")
    parser.add_argument("--memo", help="Customer-facing memo on invoice")
    parser.add_argument("--no-send", action="store_true", help="Create invoice but don't email it")
    parser.add_argument("--sms", action="store_true", help="Text payment link to customer via ClickSend")
    parser.add_argument("--sms-dry-run", action="store_true", help="Show what SMS would be sent without sending")
    parser.add_argument(
        "--podio-item-id", type=int,
        help="Podio item ID — automatically sets Invoice Status to 'Invoice Sent' after creation",
    )

    parser.add_argument("--status", action="store_true", help="Check invoice status")
    parser.add_argument("--invoice-id", help="Invoice ID for --status lookup")
    parser.add_argument("--list-recent", action="store_true", help="List recent invoices")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output raw JSON")

    args = parser.parse_args()

    if args.list_recent:
        invoices = list_recent_invoices()
        if not invoices:
            print("No invoices found.")
            return
        if args.output_json:
            print(json.dumps(invoices, indent=2))
        else:
            print(f"Recent invoices ({len(invoices)}):")
            for inv in invoices:
                print_invoice_summary(inv)
        return

    if args.status:
        if not args.invoice_id:
            print("--invoice-id required with --status", file=sys.stderr)
            sys.exit(1)
        inv = get_invoice(args.invoice_id)
        if args.output_json:
            print(json.dumps(inv, indent=2))
        else:
            print_invoice_summary(inv)
            link = inv.get("InvoiceLink")
            if link:
                print(f"  Payment link: {link}")
        return

    # --- Create invoice ---
    if not args.customer:
        print("--customer is required to create an invoice", file=sys.stderr)
        sys.exit(1)
    if not args.items or not args.amounts:
        print("At least one --item and --amount pair is required", file=sys.stderr)
        sys.exit(1)
    if len(args.items) != len(args.amounts):
        print("Each --item must have a matching --amount", file=sys.stderr)
        sys.exit(1)
    if args.sms and not args.phone:
        print("--phone is required when using --sms", file=sys.stderr)
        sys.exit(1)

    quantities = args.quantities or [1.0] * len(args.items)
    if len(quantities) < len(args.items):
        quantities.extend([1.0] * (len(args.items) - len(quantities)))

    customer = find_or_create_customer(args.customer, args.email)
    due_date = (datetime.now() + timedelta(days=args.due_days)).strftime("%Y-%m-%d")

    line_items = [
        {"description": desc, "amount": amt, "quantity": qty}
        for desc, amt, qty in zip(args.items, args.amounts, quantities)
    ]

    invoice = create_invoice(
        customer_id=customer["Id"],
        line_items=line_items,
        due_date=due_date,
        customer_email=args.email,
        send_email=not args.no_send,
        memo=args.memo,
    )

    payment_link = invoice.get("InvoiceLink")

    if args.output_json:
        print(json.dumps(invoice, indent=2))
    else:
        total = invoice.get("TotalAmt", 0)
        print(f"\nInvoice Summary:")
        print(f"  Number:   #{invoice.get('DocNumber', 'N/A')}")
        print(f"  ID:       {invoice['Id']}")
        print(f"  Total:    ${total:,.2f}")
        print(f"  Due:      {due_date}")
        print(f"  Customer: {args.customer}")
        print(f"  Emailed:  {'Yes' if not args.no_send and args.email else 'No'}")
        if payment_link:
            print(f"  Payment:  {payment_link}")
        else:
            print(f"  Payment:  (link not available — may appear in production)")

    if args.sms or args.sms_dry_run:
        if payment_link:
            send_payment_sms(
                to=args.phone,
                customer_name=args.customer,
                payment_link=payment_link,
                dry_run=args.sms_dry_run,
            )
        else:
            print("Warning: No payment link available to text. SMS skipped.", file=sys.stderr)

    # Auto-update Podio status after successful invoice creation
    if args.podio_item_id:
        update_podio_status(args.podio_item_id, "Invoice Sent")


if __name__ == "__main__":
    main()
