#!/usr/bin/env python3
"""
Poll QBO for paid invoices and update Podio lead status accordingly.

Usage:
    # Check all recent invoices and update Podio for any that are paid:
    python3 check_payments.py

    # Check more invoices:
    python3 check_payments.py --limit 50

    # Dry run — show what would be updated without touching Podio:
    python3 check_payments.py --dry-run

    # Check a specific invoice:
    python3 check_payments.py --invoice-id 1234

    # Run as a cron job (quiet mode — only prints changes):
    python3 check_payments.py --quiet
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

# Load .env BEFORE importing qbo_config/qbo_auth — they read QBO_ENVIRONMENT
# at import time to decide sandbox vs production URL.
def _load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

_load_env()

from qbo_config import get_base_url
from qbo_auth import get_access_token, get_realm_id
from podio_access import get_podio_access_token_or_none

# ---------------------------------------------------------------------------
# Podio integration (inline to avoid import issues)
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

PODIO_FIELDS = {
    "name": 276836610,
    "phone": 276836705,
    "invoice_status": 276921460,
}


def _podio_app_id() -> int:
    return int(os.environ.get("PODIO_APP_ID", "0") or "0")


def _get_podio_token() -> str | None:
    return get_podio_access_token_or_none()


def _podio_headers():
    token = _get_podio_token()
    if not token:
        return None
    return {
        "Authorization": f"OAuth2 {token}",
        "Content-Type": "application/json",
    }


def update_podio_item_status(item_id: int, status_text: str) -> bool:
    option_id = PODIO_STATUS_OPTIONS[status_text]
    headers = _podio_headers()
    if not headers:
        return False
    resp = requests.put(
        f"{PODIO_API}/item/{item_id}/value/{PODIO_INVOICE_STATUS_FIELD_ID}",
        headers=headers,
        json=option_id,
        timeout=15,
    )
    return resp.status_code in (200, 204)


def get_podio_items_with_status(status_text: str) -> list[dict]:
    """Fetch Podio items that have a specific Invoice Status."""
    option_id = PODIO_STATUS_OPTIONS.get(status_text)
    if not option_id:
        return []
    app_id = _podio_app_id()
    if not app_id:
        return []
    headers = _podio_headers()
    if not headers:
        return []

    resp = requests.post(
        f"{PODIO_API}/item/app/{app_id}/filter/",
        headers=headers,
        json={
            "filters": {
                str(PODIO_INVOICE_STATUS_FIELD_ID): [option_id],
            },
            "limit": 100,
            "sort_by": "created_on",
            "sort_desc": True,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Podio filter failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []

    items = resp.json().get("items", [])
    results = []
    for item in items:
        name = ""
        for field in item.get("fields", []):
            if field.get("field_id") == PODIO_FIELDS["name"]:
                vals = field.get("values", [])
                if vals:
                    name = vals[0].get("value", "")
        results.append({
            "item_id": item["item_id"],
            "name": name or item.get("title", ""),
        })
    return results


# ---------------------------------------------------------------------------
# QBO helpers
# ---------------------------------------------------------------------------

def _qbo_headers():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _qbo_url(endpoint: str) -> str:
    return f"{get_base_url()}/v3/company/{get_realm_id()}/{endpoint}"


def _qbo_query(sql: str) -> dict:
    resp = requests.get(
        _qbo_url("query"),
        headers=_qbo_headers(),
        params={"query": sql},
    )
    resp.raise_for_status()
    return resp.json().get("QueryResponse", {})


def get_paid_invoices(limit: int = 50) -> list[dict]:
    """Fetch recent invoices where Balance = 0 (i.e. paid)."""
    result = _qbo_query(
        f"SELECT * FROM Invoice WHERE Balance = '0' "
        f"ORDER BY MetaData.LastUpdatedTime DESC MAXRESULTS {limit}"
    )
    return result.get("Invoice", [])


def get_recent_invoices(limit: int = 50) -> list[dict]:
    result = _qbo_query(
        f"SELECT * FROM Invoice ORDER BY MetaData.CreateTime DESC MAXRESULTS {limit}"
    )
    return result.get("Invoice", [])


def get_invoice(invoice_id: str) -> dict:
    resp = requests.get(_qbo_url(f"invoice/{invoice_id}"), headers=_qbo_headers())
    resp.raise_for_status()
    return resp.json()["Invoice"]


def is_invoice_paid(inv: dict) -> bool:
    return inv.get("Balance", 1) == 0 and inv.get("TotalAmt", 0) > 0


# ---------------------------------------------------------------------------
# Matching logic: match QBO customers to Podio items by name
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def match_podio_items_to_invoices(podio_items: list[dict], paid_invoices: list[dict]) -> list[dict]:
    """
    For each Podio item with status 'Invoice Sent', check if there's a paid
    QBO invoice for the same customer name.
    """
    paid_names = {}
    for inv in paid_invoices:
        cust_name = inv.get("CustomerRef", {}).get("name", "")
        if cust_name:
            key = normalize_name(cust_name)
            if key not in paid_names:
                paid_names[key] = inv

    matches = []
    for item in podio_items:
        podio_name = normalize_name(item["name"])
        if podio_name in paid_names:
            matches.append({
                "podio_item_id": item["item_id"],
                "podio_name": item["name"],
                "invoice": paid_names[podio_name],
            })
    return matches


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Poll QBO for paid invoices and update Podio status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--limit", type=int, default=30, help="Number of invoices to check (default 30)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without changing Podio")
    parser.add_argument("--invoice-id", help="Check a specific invoice ID")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print when changes are made (for cron)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON results")
    args = parser.parse_args()

    if args.invoice_id:
        inv = get_invoice(args.invoice_id)
        paid = is_invoice_paid(inv)
        name = inv.get("CustomerRef", {}).get("name", "Unknown")
        balance = inv.get("Balance", 0)
        total = inv.get("TotalAmt", 0)
        print(f"Invoice #{inv.get('DocNumber', 'N/A')} (ID: {inv['Id']})")
        print(f"  Customer: {name}")
        print(f"  Total:    ${total:,.2f}")
        print(f"  Balance:  ${balance:,.2f}")
        print(f"  Status:   {'PAID' if paid else 'UNPAID'}")
        return

    if not args.quiet:
        print(f"Checking {args.limit} recent invoices for payments...")

    paid_invoices = get_paid_invoices(args.limit)
    if not args.quiet:
        print(f"Found {len(paid_invoices)} paid invoice(s) in QBO.")

    if not args.quiet:
        print("Fetching Podio items with 'Invoice Sent' status...")
    podio_items = get_podio_items_with_status("Invoice Sent")
    if not args.quiet:
        print(f"Found {len(podio_items)} Podio item(s) with 'Invoice Sent'.")

    matches = match_podio_items_to_invoices(podio_items, paid_invoices)

    if not matches:
        if not args.quiet:
            print("No Podio items need updating.")
        if args.output_json:
            print(json.dumps({"updated": []}, indent=2))
        return

    updated = []
    for m in matches:
        inv = m["invoice"]
        inv_num = inv.get("DocNumber", "N/A")
        total = inv.get("TotalAmt", 0)

        if args.dry_run:
            print(f"[DRY RUN] Would update Podio item {m['podio_item_id']} "
                  f"({m['podio_name']}) -> Invoice Paid  "
                  f"(QBO #{inv_num}, ${total:,.2f})")
        else:
            success = update_podio_item_status(m["podio_item_id"], "Invoice Paid")
            status_str = "OK" if success else "FAILED"
            print(f"Updated Podio item {m['podio_item_id']} ({m['podio_name']}) "
                  f"-> Invoice Paid [{status_str}]  "
                  f"(QBO #{inv_num}, ${total:,.2f})")
            updated.append({
                "podio_item_id": m["podio_item_id"],
                "name": m["podio_name"],
                "invoice_number": inv_num,
                "amount": total,
                "success": success,
            })

    if args.output_json:
        print(json.dumps({"updated": updated}, indent=2))

    if not args.quiet:
        action = "would update" if args.dry_run else "updated"
        print(f"\nDone. {len(matches)} item(s) {action}.")


if __name__ == "__main__":
    main()
