#!/usr/bin/env python3
"""
Manage customers, orders, inventory, payments, and employees in the configured
Clover merchant via the Clover REST API.

READ
    python3 clover_lookup.py --merchant-info
    python3 clover_lookup.py --list-orders [--limit 20]
    python3 clover_lookup.py --get-order ORDER_ID
    python3 clover_lookup.py --list-customers [--limit 50]
    python3 clover_lookup.py --search-customer "Devin"
    python3 clover_lookup.py --customer-history CUSTOMER_ID
    python3 clover_lookup.py --sales-summary [--from 2024-01-01] [--to 2024-01-31]
    python3 clover_lookup.py --top-services [--limit 10] [--from 2024-01-01] [--to 2024-01-31]
    python3 clover_lookup.py --list-items [--limit 200]
    python3 clover_lookup.py --list-payments [--limit 20]
    python3 clover_lookup.py --list-employees
    python3 clover_lookup.py --list-discounts
    python3 clover_lookup.py --list-tax-rates

WRITE (requires Admin-level API token)
    python3 clover_lookup.py --create-customer --first-name John --last-name Doe [--email j@x.com] [--phone 5551234567]
    python3 clover_lookup.py --update-customer CUSTOMER_ID [--first-name X] [--last-name X] [--email X] [--phone X]
    python3 clover_lookup.py --create-order --service "Full Detail:250.00" [--service "Wax:50.00"] [--customer-id ID] [--note "2022 Honda Civic, silver"]
    python3 clover_lookup.py --add-line-item --order-id ID --name "Ceramic Coating" --price 300.00
    python3 clover_lookup.py --attach-customer --order-id ID --customer-id ID
    python3 clover_lookup.py --add-order-note --order-id ID --note "Silver Honda Civic, no wheel wells"
    python3 clover_lookup.py --delete-order ORDER_ID
    python3 clover_lookup.py --create-item --name "Full Detail" --price 250.00 [--sku X]
    python3 clover_lookup.py --update-item ITEM_ID [--name X] [--price 275.00]
    python3 clover_lookup.py --refund --payment-id ID [--amount 50.00]
    python3 clover_lookup.py --apply-discount --order-id ID --percent 10 [--name "Loyal Customer"]
    python3 clover_lookup.py --create-tax-rate --name "Sales Tax" --rate 8.5

All commands accept --json for raw JSON output.

Reads credentials from environment (populated by ~/.hermes/.env):
    CLOVER_ACCESS_TOKEN   required — Admin token for write operations
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
        "Content-Type": "application/json",
    }


def _checkout_request(json_body: dict) -> dict:
    """Clover Invoicing Checkout Service — different base URL and auth header."""
    url = "https://api.clover.com/invoicingcheckoutservice/v1/checkouts"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
            "X-Clover-Merchant-Id": _merchant_id(),
        },
        json=json_body,
        timeout=TIMEOUT,
    )
    if resp.status_code == 401:
        print("error: 401 on checkout service — token rejected.", file=sys.stderr)
        sys.exit(3)
    resp.raise_for_status()
    return resp.json()


def _request(method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> dict:
    url = f"{_api_base()}/v3/merchants/{_merchant_id()}{path}"
    resp = requests.request(method, url, headers=_headers(), params=params, json=json_body, timeout=TIMEOUT)
    if resp.status_code == 401:
        print("error: 401 Unauthorized — token rejected. Ensure you used an Admin API token.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 403:
        print("error: 403 Forbidden — token lacks write permissions. Re-generate from an Admin account.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 404:
        print(f"error: 404 Not Found — check IDs and that the resource exists.", file=sys.stderr)
        sys.exit(4)
    resp.raise_for_status()
    return resp.json()


def _dollars_to_cents(val: str | float) -> int:
    try:
        return round(float(val) * 100)
    except (TypeError, ValueError):
        print(f"error: invalid price '{val}' — use dollars, e.g. 250.00", file=sys.stderr)
        sys.exit(1)


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


def _date_to_ms(date_str: str, end_of_day: bool = False) -> int:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp() * 1000)
    except ValueError:
        print(f"error: invalid date '{date_str}' — use YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# READ commands
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
    if data.get("note"):
        print(f"Note     : {data.get('note')}")
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


def customer_history(customer_id: str, as_json: bool) -> None:
    data = _request("GET", f"/customers/{customer_id}/orders", params={"expand": "lineItems"})
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No orders found for this customer.")
        return
    total = sum(o.get("total") or 0 for o in elements)
    print(f"{len(elements)} order(s)  lifetime value: {_cents_to_dollars(total)}")
    for o in elements:
        print(f"- {o.get('id')}  {_ms_to_iso(o.get('createdTime'))}  {_cents_to_dollars(o.get('total'))}  state={o.get('state', '')}")


def sales_summary(from_date: str | None, to_date: str | None, as_json: bool) -> None:
    params: dict = {"limit": 1000}
    filters = []
    if from_date:
        filters.append(f"createdTime>={_date_to_ms(from_date)}")
    if to_date:
        filters.append(f"createdTime<={_date_to_ms(to_date, end_of_day=True)}")
    if filters:
        params["filter"] = filters

    data = _request("GET", "/payments", params=params)
    elements = data.get("elements", [])

    if as_json:
        print(json.dumps(elements, indent=2))
        return

    if not elements:
        print("No payments found for that period.")
        return

    total = sum(p.get("amount") or 0 for p in elements if p.get("result") not in ("VOIDED", "VOID"))
    refunds = sum(p.get("amount") or 0 for p in elements if p.get("result") in ("VOIDED", "VOID"))
    by_day: dict = {}
    for p in elements:
        if p.get("result") in ("VOIDED", "VOID"):
            continue
        day = _ms_to_iso(p.get("createdTime"))[:10]
        by_day[day] = by_day.get(day, 0) + (p.get("amount") or 0)

    period = f"{from_date or 'all time'} → {to_date or 'now'}"
    print(f"Period   : {period}")
    print(f"Revenue  : {_cents_to_dollars(total)}  ({len(elements)} transactions)")
    if refunds:
        print(f"Voided   : {_cents_to_dollars(refunds)}")
    if by_day:
        print("By day:")
        for day in sorted(by_day):
            print(f"  {day}  {_cents_to_dollars(by_day[day])}")


def top_services(limit: int, from_date: str | None, to_date: str | None, as_json: bool) -> None:
    params: dict = {"limit": 500, "expand": "lineItems"}
    filters = []
    if from_date:
        filters.append(f"createdTime>={_date_to_ms(from_date)}")
    if to_date:
        filters.append(f"createdTime<={_date_to_ms(to_date, end_of_day=True)}")
    if filters:
        params["filter"] = filters

    data = _request("GET", "/orders", params=params)
    tally: dict = {}
    for o in data.get("elements", []):
        for li in (o.get("lineItems") or {}).get("elements", []):
            name = li.get("name") or "(unnamed)"
            price = li.get("price") or 0
            if name not in tally:
                tally[name] = {"count": 0, "revenue": 0}
            tally[name]["count"] += 1
            tally[name]["revenue"] += price

    ranked = sorted(tally.items(), key=lambda x: x[1]["revenue"], reverse=True)[:limit]

    if as_json:
        print(json.dumps([{"name": k, **v} for k, v in ranked], indent=2))
        return
    if not ranked:
        print("No line items found.")
        return
    print(f"{'Service':<35} {'Count':>6}  {'Revenue':>10}")
    print("-" * 56)
    for name, stats in ranked:
        print(f"{name[:35]:<35} {stats['count']:>6}  {_cents_to_dollars(stats['revenue']):>10}")


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


def list_discounts(as_json: bool) -> None:
    data = _request("GET", "/discounts")
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No discounts configured.")
        return
    for d in elements:
        val = f"{d.get('percentage')}%" if d.get("percentage") else _cents_to_dollars(d.get("amount"))
        print(f"- {d.get('id')}  {d.get('name', '?')}  {val}")


def list_tax_rates(as_json: bool) -> None:
    data = _request("GET", "/tax_rates")
    elements = data.get("elements", [])
    if as_json:
        print(json.dumps(elements, indent=2))
        return
    if not elements:
        print("No tax rates configured.")
        return
    for t in elements:
        rate_pct = (t.get("rate") or 0) / 100
        print(f"- {t.get('id')}  {t.get('name', '?')}  {rate_pct:.2f}%")


# ---------------------------------------------------------------------------
# WRITE commands
# ---------------------------------------------------------------------------

def payment_link(services: list[str], customer_email: str | None, as_json: bool) -> None:
    line_items = []
    for s in services:
        if ":" not in s:
            print(f"error: --service must be 'Name:price', got '{s}'", file=sys.stderr)
            sys.exit(1)
        name, price_str = s.rsplit(":", 1)
        line_items.append({"name": name.strip(), "price": _dollars_to_cents(price_str.strip()), "unitQty": 1000})
    body: dict = {"shoppingCart": {"lineItems": line_items}}
    if customer_email:
        body["customer"] = {"email": customer_email}
    else:
        body["customer"] = {}
    data = _checkout_request(body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Payment link : {data.get('href')}")
    print(f"Expires      : {data.get('expirationTime', '')}")


def create_customer(first_name: str, last_name: str, email: str | None, phone: str | None, as_json: bool) -> None:
    if not first_name and not last_name:
        print("error: at least one of --first-name or --last-name is required.", file=sys.stderr)
        sys.exit(1)
    body: dict = {}
    if first_name:
        body["firstName"] = first_name
    if last_name:
        body["lastName"] = last_name
    if email:
        body["emailAddresses"] = {"elements": [{"emailAddress": email}]}
    if phone:
        body["phoneNumbers"] = {"elements": [{"phoneNumber": phone}]}
    data = _request("POST", "/customers", json_body=body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    name = " ".join(filter(None, [data.get("firstName"), data.get("lastName")])) or "(unnamed)"
    print(f"Created customer: {data.get('id')}  {name}")
    if email:
        print(f"  email : {email}")
    if phone:
        print(f"  phone : {phone}")


def update_customer(customer_id: str, first_name: str, last_name: str, email: str | None, phone: str | None, as_json: bool) -> None:
    body: dict = {}
    if first_name:
        body["firstName"] = first_name
    if last_name:
        body["lastName"] = last_name
    if body:
        _request("POST", f"/customers/{customer_id}", json_body=body)
    if email:
        _request("POST", f"/customers/{customer_id}/emailAddresses", json_body={"emailAddress": email})
    if phone:
        _request("POST", f"/customers/{customer_id}/phoneNumbers", json_body={"phoneNumber": phone})
    if as_json:
        data = _request("GET", f"/customers/{customer_id}", params={"expand": "emailAddresses,phoneNumbers"})
        print(json.dumps(data, indent=2))
        return
    print(f"Updated customer {customer_id}")


def create_order(services: list[str], customer_id: str | None, note: str | None, as_json: bool) -> None:
    # Parse "Name:price" pairs
    line_items = []
    for s in services:
        if ":" not in s:
            print(f"error: --service must be 'Name:price', got '{s}'", file=sys.stderr)
            sys.exit(1)
        name, price_str = s.rsplit(":", 1)
        line_items.append((name.strip(), _dollars_to_cents(price_str.strip())))

    order_body: dict = {"state": "open"}
    if note:
        order_body["note"] = note
    order = _request("POST", "/orders", json_body=order_body)
    order_id = order["id"]

    for name, cents in line_items:
        _request("POST", f"/orders/{order_id}/line_items", json_body={"name": name, "price": cents, "unitQty": 1000})

    if customer_id:
        _request("POST", f"/orders/{order_id}/customers", json_body={"id": customer_id})

    if as_json:
        result = _request("GET", f"/orders/{order_id}", params={"expand": "lineItems,customers"})
        print(json.dumps(result, indent=2))
        return

    total = sum(c for _, c in line_items)
    print(f"Created order: {order_id}")
    if note:
        print(f"  note     : {note}")
    for name, cents in line_items:
        print(f"  item     : {name}  {_cents_to_dollars(cents)}")
    print(f"  total    : {_cents_to_dollars(total)}")
    if customer_id:
        print(f"  customer : {customer_id}")
    # Auto-generate a hosted checkout link for the customer
    try:
        checkout_items = [{"name": n, "price": c, "unitQty": 1000} for n, c in line_items]
        checkout = _checkout_request({"customer": {}, "shoppingCart": {"lineItems": checkout_items}})
        checkout_url = checkout.get("href", "")
        if checkout_url:
            print(f"  pay link : {checkout_url}")
            print(f"  expires  : {checkout.get('expirationTime', '')}")
            print("Send this link to the customer via Gmail or ClickSend SMS to collect payment.")
    except Exception:
        print("note: could not generate payment link — send invoice manually via Clover dashboard.")


def add_line_item(order_id: str, name: str, price_dollars: str, as_json: bool) -> None:
    cents = _dollars_to_cents(price_dollars)
    data = _request("POST", f"/orders/{order_id}/line_items", json_body={"name": name, "price": cents, "unitQty": 1000})
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Added line item '{name}' ({_cents_to_dollars(cents)}) to order {order_id}  item_id={data.get('id')}")


def attach_customer(order_id: str, customer_id: str, as_json: bool) -> None:
    data = _request("POST", f"/orders/{order_id}/customers", json_body={"id": customer_id})
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Attached customer {customer_id} to order {order_id}")


def add_order_note(order_id: str, note: str, as_json: bool) -> None:
    data = _request("POST", f"/orders/{order_id}", json_body={"note": note})
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Added note to order {order_id}: {note}")


def delete_order(order_id: str) -> None:
    _request("DELETE", f"/orders/{order_id}")
    print(f"Deleted order {order_id}")


def create_item(name: str, price_dollars: str, sku: str | None, as_json: bool) -> None:
    body: dict = {"name": name, "price": _dollars_to_cents(price_dollars)}
    if sku:
        body["sku"] = sku
    data = _request("POST", "/items", json_body=body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Created item: {data.get('id')}  {name}  {_cents_to_dollars(data.get('price'))}")


def update_item(item_id: str, name: str | None, price_dollars: str | None, as_json: bool) -> None:
    body: dict = {}
    if name:
        body["name"] = name
    if price_dollars:
        body["price"] = _dollars_to_cents(price_dollars)
    if not body:
        print("error: provide at least --name or --price to update.", file=sys.stderr)
        sys.exit(1)
    data = _request("POST", f"/items/{item_id}", json_body=body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Updated item {item_id}")
    if name:
        print(f"  name  : {name}")
    if price_dollars:
        print(f"  price : {_cents_to_dollars(_dollars_to_cents(price_dollars))}")


def refund_payment(payment_id: str, amount_dollars: str | None, as_json: bool) -> None:
    body: dict = {"payment": {"id": payment_id}}
    if amount_dollars:
        body["amount"] = _dollars_to_cents(amount_dollars)
        body["fullRefund"] = False
    else:
        body["fullRefund"] = True
    data = _request("POST", "/refunds", json_body=body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    refund_amount = data.get("amount")
    print(f"Refund issued: {data.get('id')}  {_cents_to_dollars(refund_amount)}  payment={payment_id}")


def apply_discount(order_id: str, percent: float, name: str | None, as_json: bool) -> None:
    body: dict = {"percentage": int(percent)}
    if name:
        body["name"] = name
    data = _request("POST", f"/orders/{order_id}/discounts", json_body=body)
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Applied {int(percent)}% discount to order {order_id}  discount_id={data.get('id')}")


def create_tax_rate(name: str, rate_pct: float, as_json: bool) -> None:
    basis_points = round(rate_pct * 100)
    data = _request("POST", "/tax_rates", json_body={"name": name, "rate": basis_points})
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Created tax rate: {data.get('id')}  {name}  {rate_pct:.2f}%")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Clover POS — read and write via REST API")
    g = parser.add_mutually_exclusive_group(required=True)

    # Read
    g.add_argument("--merchant-info", action="store_true")
    g.add_argument("--list-orders", action="store_true")
    g.add_argument("--get-order", metavar="ORDER_ID")
    g.add_argument("--list-customers", action="store_true")
    g.add_argument("--search-customer", metavar="QUERY")
    g.add_argument("--customer-history", metavar="CUSTOMER_ID")
    g.add_argument("--sales-summary", action="store_true")
    g.add_argument("--top-services", action="store_true")
    g.add_argument("--list-items", action="store_true")
    g.add_argument("--list-payments", action="store_true")
    g.add_argument("--list-employees", action="store_true")
    g.add_argument("--list-discounts", action="store_true")
    g.add_argument("--list-tax-rates", action="store_true")

    # Write
    g.add_argument("--payment-link", action="store_true", help="Generate a hosted Clover checkout URL (no order record)")
    g.add_argument("--create-customer", action="store_true")
    g.add_argument("--update-customer", metavar="CUSTOMER_ID")
    g.add_argument("--create-order", action="store_true")
    g.add_argument("--add-line-item", action="store_true")
    g.add_argument("--attach-customer", action="store_true")
    g.add_argument("--add-order-note", action="store_true")
    g.add_argument("--delete-order", metavar="ORDER_ID")
    g.add_argument("--create-item", action="store_true")
    g.add_argument("--update-item", metavar="ITEM_ID")
    g.add_argument("--refund", action="store_true")
    g.add_argument("--apply-discount", action="store_true")
    g.add_argument("--create-tax-rate", action="store_true")

    # Shared flags
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")

    # Customer fields
    parser.add_argument("--first-name", default="")
    parser.add_argument("--last-name", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--phone", default="")

    # Order / item fields
    parser.add_argument("--order-id")
    parser.add_argument("--customer-id")
    parser.add_argument("--note")
    parser.add_argument("--service", action="append", dest="services", metavar="Name:price")
    parser.add_argument("--name")
    parser.add_argument("--price", metavar="DOLLARS")
    parser.add_argument("--sku")

    # Payment / discount / tax fields
    parser.add_argument("--payment-id")
    parser.add_argument("--amount", metavar="DOLLARS")
    parser.add_argument("--percent", type=float)
    parser.add_argument("--rate", type=float, metavar="PERCENT")
    parser.add_argument("--discount-id")

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
        elif args.customer_history:
            customer_history(args.customer_history, args.json)
        elif args.sales_summary:
            sales_summary(args.from_date, args.to_date, args.json)
        elif args.top_services:
            top_services(limit, args.from_date, args.to_date, args.json)
        elif args.list_items:
            list_items(limit, args.json)
        elif args.list_payments:
            list_payments(limit, args.json)
        elif args.list_employees:
            list_employees(args.json)
        elif args.list_discounts:
            list_discounts(args.json)
        elif args.list_tax_rates:
            list_tax_rates(args.json)
        elif args.payment_link:
            if not args.services:
                print("error: --payment-link requires at least one --service 'Name:price'", file=sys.stderr)
                return 1
            payment_link(args.services, args.email or None, args.json)
        elif args.create_customer:
            create_customer(args.first_name, args.last_name, args.email or None, args.phone or None, args.json)
        elif args.update_customer:
            update_customer(args.update_customer, args.first_name, args.last_name, args.email or None, args.phone or None, args.json)
        elif args.create_order:
            if not args.services:
                print("error: --create-order requires at least one --service 'Name:price'", file=sys.stderr)
                return 1
            create_order(args.services, args.customer_id, args.note, args.json)
        elif args.add_line_item:
            if not args.order_id or not args.name or not args.price:
                print("error: --add-line-item requires --order-id, --name, and --price", file=sys.stderr)
                return 1
            add_line_item(args.order_id, args.name, args.price, args.json)
        elif args.attach_customer:
            if not args.order_id or not args.customer_id:
                print("error: --attach-customer requires --order-id and --customer-id", file=sys.stderr)
                return 1
            attach_customer(args.order_id, args.customer_id, args.json)
        elif args.add_order_note:
            if not args.order_id or not args.note:
                print("error: --add-order-note requires --order-id and --note", file=sys.stderr)
                return 1
            add_order_note(args.order_id, args.note, args.json)
        elif args.delete_order:
            delete_order(args.delete_order)
        elif args.create_item:
            if not args.name or not args.price:
                print("error: --create-item requires --name and --price", file=sys.stderr)
                return 1
            create_item(args.name, args.price, args.sku, args.json)
        elif args.update_item:
            update_item(args.update_item, args.name, args.price, args.json)
        elif args.refund:
            if not args.payment_id:
                print("error: --refund requires --payment-id", file=sys.stderr)
                return 1
            refund_payment(args.payment_id, args.amount, args.json)
        elif args.apply_discount:
            if not args.order_id or args.percent is None:
                print("error: --apply-discount requires --order-id and --percent", file=sys.stderr)
                return 1
            apply_discount(args.order_id, args.percent, args.name, args.json)
        elif args.create_tax_rate:
            if not args.name or args.rate is None:
                print("error: --create-tax-rate requires --name and --rate", file=sys.stderr)
                return 1
            create_tax_rate(args.name, args.rate, args.json)
    except requests.HTTPError as exc:
        print(f"error: HTTP {exc.response.status_code}: {exc.response.text[:500]}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
