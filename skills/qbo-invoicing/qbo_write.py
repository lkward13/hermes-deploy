#!/usr/bin/env python3
"""
QuickBooks Online — uniform writer (create / update / delete / void / send).

QBO's write API is uniform across entities, so one tool covers them all:
  create  POST /v3/company/{realm}/{Entity}                 (JSON body)
  update  POST /v3/company/{realm}/{Entity}                 (sparse; Id+SyncToken auto-added)
  delete  POST /v3/company/{realm}/{Entity}?operation=delete (transaction entities)
  void    POST /v3/company/{realm}/{Entity}?operation=void   (invoices, payments, …)
  deactivate  sparse-update Active=false                     (name-list entities: Customer/Vendor/Item — QBO has no hard delete for these)
  send    POST /v3/company/{realm}/{Entity}/{id}/send        (email an invoice/estimate)

The agent supplies the JSON body; this tool handles auth (auto-refresh), the
realm path, minorversion, and — for update/delete/void — fetching the current
SyncToken so the caller never has to.

Examples:
  qbo_write.py create Estimate '{"CustomerRef":{"value":"58"},"Line":[{"Amount":1200,"DetailType":"SalesItemLineDetail","SalesItemLineDetail":{"ItemRef":{"value":"1"}}}]}'
  qbo_write.py create Bill '{"VendorRef":{"value":"56"},"Line":[{"Amount":300,"DetailType":"AccountBasedExpenseLineDetail","AccountBasedExpenseLineDetail":{"AccountRef":{"value":"7"}}}]}'
  qbo_write.py create Vendor '{"DisplayName":"Acme Supply","PrimaryEmailAddr":{"Address":"ap@acme.com"}}'
  qbo_write.py update Invoice 145 '{"CustomerMemo":{"value":"Thanks for your business"}}'
  qbo_write.py void Invoice 145
  qbo_write.py delete Estimate 200
  qbo_write.py deactivate Item 12
  qbo_write.py send Invoice 145 --email customer@example.com

Read with qbo_lookup.py to find Ids first (e.g. `qbo_lookup.py list Vendor --search Acme`).
By default prints a short result line; add --json for the full returned object.

DESTRUCTIVE ops (delete/void) are irreversible in QBO — the agent's approval
gate should confirm them with the owner first.
"""

import argparse
import json
import sys

import requests

from qbo_auth import get_access_token, get_realm_id
from qbo_config import get_base_url

TIMEOUT = 30
MINOR_VERSION = "73"

# Name-list entities: QBO has no hard delete — deactivate (Active=false) instead.
NAME_LIST = {"Customer", "Vendor", "Employee", "Item", "Account", "Class",
             "Department", "Term", "PaymentMethod", "TaxCode", "TaxRate"}
# Transaction entities that support void (vs delete).
VOIDABLE = {"Invoice", "Payment", "SalesReceipt", "BillPayment", "Purchase"}

# Canonical casing for the entity path/key.
KNOWN = NAME_LIST | VOIDABLE | {
    "Estimate", "CreditMemo", "RefundReceipt", "Bill", "VendorCredit",
    "PurchaseOrder", "Deposit", "Transfer", "JournalEntry", "TimeActivity", "Budget",
}


def _canon(entity: str) -> str:
    return next((e for e in KNOWN if e.lower() == entity.lower()), entity)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{get_base_url()}/v3/company/{get_realm_id()}/{path}"


def _handle(resp: requests.Response) -> dict:
    if resp.status_code == 401:
        print("error: 401 Unauthorized — QBO token rejected. Reconnect QuickBooks in the NoDesk portal.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 403:
        print("error: 403 Forbidden — the connected QBO account lacks permission to write that.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code >= 400:
        try:
            fault = resp.json().get("Fault", {})
            errs = "; ".join(e.get("Message", "") + (f" ({e.get('Detail')})" if e.get("Detail") else "")
                             for e in fault.get("Error", []))
            print(f"error: QBO {resp.status_code}: {errs or resp.text[:400]}", file=sys.stderr)
        except ValueError:
            print(f"error: QBO {resp.status_code}: {resp.text[:400]}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def _parse_body(raw: str) -> dict:
    if raw == "-":
        raw = sys.stdin.read()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: body is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(body, dict):
        print("error: body must be a JSON object", file=sys.stderr)
        sys.exit(1)
    return body


def _fetch(entity: str, obj_id: str) -> dict:
    """GET a record (needed for its current SyncToken before update/delete/void)."""
    resp = requests.get(
        _url(entity.lower()) + f"/{obj_id}",
        headers={k: v for k, v in _headers().items() if k != "Content-Type"},
        params={"minorversion": MINOR_VERSION},
        timeout=TIMEOUT,
    )
    data = _handle(resp)
    return data.get(entity) or next((v for v in data.values() if isinstance(v, dict)), {})


def _post(entity: str, body: dict, operation: str | None = None) -> dict:
    params = {"minorversion": MINOR_VERSION}
    if operation:
        params["operation"] = operation
    resp = requests.post(_url(entity.lower()), headers=_headers(), params=params, json=body, timeout=TIMEOUT)
    return _handle(resp)


def _result(entity: str, data: dict, as_json: bool, verb: str) -> None:
    obj = data.get(entity) or next((v for v in data.values() if isinstance(v, dict)), data)
    if as_json:
        print(json.dumps(obj, indent=2))
        return
    rid = obj.get("Id", "?")
    name = obj.get("DisplayName") or obj.get("Name") or (obj.get("CustomerRef") or {}).get("name", "")
    doc = obj.get("DocNumber", "")
    total = obj.get("TotalAmt")
    bits = [f"{verb} {entity} {rid}"]
    if doc:
        bits.append(f"#{doc}")
    if name:
        bits.append(name)
    if total is not None:
        bits.append(f"${float(total):,.2f}")
    print("  ".join(bits))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_create(args) -> None:
    entity = _canon(args.entity)
    body = _parse_body(args.body)
    _result(entity, _post(entity, body), args.json, "Created")


def cmd_update(args) -> None:
    entity = _canon(args.entity)
    fields = _parse_body(args.body)
    current = _fetch(entity, args.id)
    if not current.get("SyncToken"):
        print(f"error: could not read {entity} {args.id} (needed for SyncToken)", file=sys.stderr)
        sys.exit(4)
    body = {**fields, "Id": args.id, "SyncToken": current["SyncToken"], "sparse": True}
    _result(entity, _post(entity, body), args.json, "Updated")


def cmd_delete(args) -> None:
    entity = _canon(args.entity)
    if entity in NAME_LIST:
        print(f"error: QBO has no hard delete for {entity} — use `deactivate {entity} {args.id}` instead.", file=sys.stderr)
        sys.exit(1)
    current = _fetch(entity, args.id)
    body = {"Id": args.id, "SyncToken": current.get("SyncToken", "0")}
    _result(entity, _post(entity, body, operation="delete"), args.json, "Deleted")


def cmd_void(args) -> None:
    entity = _canon(args.entity)
    current = _fetch(entity, args.id)
    body = {"Id": args.id, "SyncToken": current.get("SyncToken", "0")}
    _result(entity, _post(entity, body, operation="void"), args.json, "Voided")


def cmd_deactivate(args) -> None:
    entity = _canon(args.entity)
    current = _fetch(entity, args.id)
    body = {"Id": args.id, "SyncToken": current.get("SyncToken", "0"), "Active": False, "sparse": True}
    _result(entity, _post(entity, body), args.json, "Deactivated")


def cmd_send(args) -> None:
    entity = _canon(args.entity)
    params = {"minorversion": MINOR_VERSION}
    if args.email:
        params["sendTo"] = args.email
    resp = requests.post(
        _url(f"{entity.lower()}/{args.id}/send"),
        headers={k: v for k, v in _headers().items() if k != "Content-Type"},
        params=params,
        timeout=TIMEOUT,
    )
    data = _handle(resp)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        to = args.email or "the email on file"
        print(f"Sent {entity} {args.id} to {to}")


def main() -> int:
    p = argparse.ArgumentParser(description="QuickBooks Online — create / update / delete / void / send")
    p.add_argument("--json", action="store_true", help="print the full returned object")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="create a record (POST entity)")
    c.add_argument("entity")
    c.add_argument("body", help="JSON object (or '-' to read stdin)")

    u = sub.add_parser("update", help="sparse-update fields (Id+SyncToken auto)")
    u.add_argument("entity")
    u.add_argument("id")
    u.add_argument("body", help="JSON object of fields to change (or '-' for stdin)")

    d = sub.add_parser("delete", help="delete a transaction record (irreversible)")
    d.add_argument("entity")
    d.add_argument("id")

    v = sub.add_parser("void", help="void a transaction (invoice/payment/…)")
    v.add_argument("entity")
    v.add_argument("id")

    da = sub.add_parser("deactivate", help="deactivate a name-list record (Customer/Vendor/Item/…)")
    da.add_argument("entity")
    da.add_argument("id")

    s = sub.add_parser("send", help="email an invoice/estimate")
    s.add_argument("entity")
    s.add_argument("id")
    s.add_argument("--email", help="recipient (defaults to the email on the record)")

    args = p.parse_args()
    try:
        {
            "create": cmd_create,
            "update": cmd_update,
            "delete": cmd_delete,
            "void": cmd_void,
            "deactivate": cmd_deactivate,
            "send": cmd_send,
        }[args.cmd](args)
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
