#!/usr/bin/env python3
"""
Look up orders, customers, items, payments, and employees in the configured
Clover merchant via the Clover REST API.

Usage:
    python3 clover_lookup.py --merchant-info
    python3 clover_lookup.py --list-orders [--limit 20]
    python3 clover_lookup.py --get-order ORDER_ID
    python3 clover_lookup.py --list-customers [--limit 50]
    python3 clover_lookup.py --search-customer "Devin"
    python3 clover_lookup.py --list-items [--limit 200]
    python3 clover_lookup.py --list-payments [--limit 20]
    python3 clover_lookup.py --list-employees
    python3 clover_lookup.py --list-orders --json

Reads credentials from environment (typically populated by ~/.hermes/.env):
    CLOVER_ACCESS_TOKEN   required
    CLOVER_MERCHANT_ID    required
    CLOVER_SANDBOX        optional ("true" -> sandbox host)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

TIMEOUT = 20


def _api_base() -> str:
    sandbox = os.environ.get("CLOVER_SANDBOX", "").strip().lower() == "true"
    return "https://apisandbox.dev.clover.com" if sandbox else "https://api.clover.com"


def _access_token() -> str:
    token = os.environ.get("CLOVER_ACCESS_TOKEN", "").strip()
    if not token:
        print("error: CLOVER_ACCESS_TOKEN not set. Connect Clover in the NoDesk portal.", file=sys.stderr)
        sys.exit(2)
    return token


def _merchant_id() -> str:
    mid = os.environ.get("CLOVER_MERCHANT_ID", "").strip()
    if not mid:
        print("error: CLOVER_MERCHANT_ID not set. Reconnect Clover in the NoDesk portal.", file=sys.stderr)
        sys.exit(2)
    return mid


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_access_token()}",
        "Accept": "application/json",
    }


def _request(method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> dict:
    url = f"{_api_base()}/v3/merchants/{_merchant_id()}{path}"
    resp = requests.request(method, url, headers=_headers(), params=params, json=json_body, timeout=TIMEOUT)
    if resp.status_code == 401:
        print("error: 401 Unauthorized — Clover access token rejected. Trigger a NoDesk credential sync.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 404:
        print(f"error: 404 Not Found at {url}. Check merchant ID and that the resource exists.", file=sys.stderr)
        sys.exit(4)
    resp.raise_for_status()
    return resp.json()


def _request_root(path: str, params: dict | None = None) -> dict:
    """For endpoints that aren't merchant-scoped (rare)."""
    url = f"{_api_base()}{path}"
    resp = requests.request("GET", url, headers=_headers(), params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _cents_to_dollars(cents) -> str:
    if cents is None:
        return ""
    try:
        return f"${int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return str(cents)


def _ms_to_iso(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(ms)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def merchant_info(as_json: bool) -> None:
    data = _request("GET", "")
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Merchant : {data.get('name', '?')}")
    print(f"ID       : {data.get('id', '?')}")
    addr = data.get("address") or {}
    if addr:
        line = ", ".join(filter(None, [addr.get("address1"), addr.get("city"), addr.get("state"), addr.get("zip")]))
        print(f"Address  : {line}")
    print(f"Phone    : {data.get('phoneNumber', '')}")
    print(f"Website  : {data.get('website', '')}")
    print(f"Sandbox  : {'yes' if 'sandbox' in _api_base() else 'no'}")


def list_orders(limit: int, as_json: bool) -> None:
    data = _request("GET", "/orders", params={"limit": limit, "expand": "lineItems,payments"})
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No orders found.")
        return
    for o in elements:
        print(f"- {o.get('id')}  {_ms_to_iso(o.get('createdTime'))}  {_cents_to_dollars(o.get('total'))}  state={o.get('state', '')}  title={o.get('title', '')}")


def get_order(order_id: str, as_json: bool) -> None:
    data = _request("GET", f"/orders/{order_id}", params={"expand": "lineItems,payments,customers"})
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Order    : {data.get('id')}")
    print(f"Created  : {_ms_to_iso(data.get('createdTime'))}")
    print(f"Total    : {_cents_to_dollars(data.get('total'))}")
    print(f"State    : {data.get('state', '')}")
    line_items = (data.get("lineItems") or {}).get("elements") or []
    if line_items:
        print("Items:")
        for li in line_items:
            print(f"  - {li.get('name', '?')}  {_cents_to_dollars(li.get('price'))}")
    payments = (data.get("payments") or {}).get("elements") or []
    if payments:
        print("Payments:")
        for p in payments:
            print(f"  - {p.get('id')}  {_cents_to_dollars(p.get('amount'))}  result={p.get('result', '')}")


def list_customers(limit: int, as_json: bool) -> None:
    data = _request("GET", "/customers", params={"limit": limit, "expand": "emailAddresses,phoneNumbers"})
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No customers found.")
        return
    for c in elements:
        phones = ", ".join(p.get("phoneNumber", "") for p in (c.get("phoneNumbers") or {}).get("elements", []))
        emails = ", ".join(e.get("emailAddress", "") for e in (c.get("emailAddresses") or {}).get("elements", []))
        name = " ".join(filter(None, [c.get("firstName"), c.get("lastName")])) or "(unnamed)"
        print(f"- {c.get('id')}  {name}  {phones}  {emails}")


def search_customer(query: str, as_json: bool) -> None:
    # Clover doesn't have a single search endpoint; fetch a page and filter client-side.
    data = _request("GET", "/customers", params={"limit": 200, "expand": "emailAddresses,phoneNumbers"})
    needle = query.strip().lower()
    digits = "".join(ch for ch in query if ch.isdigit())
    matches = []
    for c in data.get("elements", []):
        name = " ".join(filter(None, [c.get("firstName"), c.get("lastName")])).lower()
        phones = [p.get("phoneNumber", "") for p in (c.get("phoneNumbers") or {}).get("elements", [])]
        emails = [e.get("emailAddress", "") for e in (c.get("emailAddresses") or {}).get("elements", [])]
        hit = needle in name
        if not hit and digits:
            hit = any(digits in "".join(ch for ch in p if ch.isdigit()) for p in phones)
        if not hit:
            hit = any(needle in (e or "").lower() for e in emails)
        if hit:
            matches.append(c)

    if as_json:
        print(json.dumps(matches, indent=2))
        return
    if not matches:
        print(f"No customers matched '{query}'.")
        return
    for c in matches:
        phones = ", ".join(p.get("phoneNumber", "") for p in (c.get("phoneNumbers") or {}).get("elements", []))
        emails = ", ".join(e.get("emailAddress", "") for e in (c.get("emailAddresses") or {}).get("elements", []))
        name = " ".join(filter(None, [c.get("firstName"), c.get("lastName")])) or "(unnamed)"
        print(f"- {c.get('id')}  {name}  {phones}  {emails}")


def list_items(limit: int, as_json: bool) -> None:
    data = _request("GET", "/items", params={"limit": limit})
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No items in inventory.")
        return
    for i in elements:
        print(f"- {i.get('id')}  {i.get('name', '?')}  {_cents_to_dollars(i.get('price'))}  sku={i.get('sku', '')}  hidden={i.get('hidden', False)}")


def list_payments(limit: int, as_json: bool) -> None:
    data = _request("GET", "/payments", params={"limit": limit})
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No payments found.")
        return
    for p in elements:
        print(f"- {p.get('id')}  {_ms_to_iso(p.get('createdTime'))}  {_cents_to_dollars(p.get('amount'))}  result={p.get('result', '')}  tender={(p.get('tender') or {}).get('label', '')}")


def list_employees(as_json: bool) -> None:
    data = _request("GET", "/employees")
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No employees found.")
        return
    for e in elements:
        print(f"- {e.get('id')}  {e.get('name', '?')}  role={e.get('role', '')}  nickname={e.get('nickname', '')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Clover POS lookup")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--merchant-info", action="store_true", help="Print merchant name, address, phone")
    g.add_argument("--list-orders", action="store_true", help="List recent orders")
    g.add_argument("--get-order", metavar="ORDER_ID", help="Get a single order with line items + payments")
    g.add_argument("--list-customers", action="store_true", help="List customers")
    g.add_argument("--search-customer", metavar="QUERY", help="Search customers by name, phone, or email")
    g.add_argument("--list-items", action="store_true", help="List inventory items")
    g.add_argument("--list-payments", action="store_true", help="List recent payments")
    g.add_argument("--list-employees", action="store_true", help="List employees")

    parser.add_argument("--limit", type=int, default=20, help="Page size for list commands (default 20, max 1000)")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of summary")
    args = parser.parse_args()

    limit = max(1, min(args.limit, 1000))

    try:
        if args.merchant_info:
            merchant_info(args.json)
        elif args.list_orders:
            list_orders(limit, args.json)
        elif args.get_order:
            get_order(args.get_order, args.json)
        elif args.list_customers:
            list_customers(limit, args.json)
        elif args.search_customer:
            search_customer(args.search_customer, args.json)
        elif args.list_items:
            list_items(limit, args.json)
        elif args.list_payments:
            list_payments(limit, args.json)
        elif args.list_employees:
            list_employees(args.json)
    except requests.HTTPError as exc:
        print(f"error: HTTP {exc.response.status_code}: {exc.response.text[:500]}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
