#!/usr/bin/env python3
"""
QuickBooks Online — read-only lookups, queries, and financial reports.

The broad "read everything" companion to create_invoice.py (writes) and
check_payments.py (reconciliation). Reuses qbo_auth.py for OAuth (auto-refresh)
and qbo_config.py for the sandbox/prod base URL. Read-only: only GET requests.

Four subcommands cover essentially the whole Accounting API surface:

  query   — run any QBO SQL (the universal escape hatch)
  list    — SELECT * FROM <Entity> with common filters (convenience over query)
  get     — read a single record by Id
  report  — run any QBO financial report (P&L, balance sheet, AR aging, …)

Examples:
  python3 qbo_lookup.py list Customer --search "Smith"
  python3 qbo_lookup.py list Invoice --where "Balance > '0'" --limit 50   # unpaid
  python3 qbo_lookup.py list Bill --where "Balance > '0'"                  # unpaid bills (A/P)
  python3 qbo_lookup.py get Invoice 145
  python3 qbo_lookup.py query "SELECT * FROM Vendor WHERE Active = true"
  python3 qbo_lookup.py report ProfitAndLoss --from 2026-01-01 --to 2026-03-31
  python3 qbo_lookup.py report BalanceSheet
  python3 qbo_lookup.py report AgedReceivables
  python3 qbo_lookup.py report CustomerSales --from 2026-01-01
  python3 qbo_lookup.py company

Add --json to any command for raw JSON.

Reads credentials from ~/.hermes/.env (QBO_* vars) + qbo_tokens.json.
"""

import argparse
import json
import sys

import requests

from qbo_auth import get_access_token, get_realm_id
from qbo_config import get_base_url

TIMEOUT = 30
MINOR_VERSION = "73"  # pin a recent QBO API minor version for stable behavior

# Entities the QBO Accounting API exposes to read via SELECT * FROM <name>.
# (Documented in SKILL.md; this set powers `list` validation + help.)
ENTITIES = [
    # Sales / A/R
    "Customer", "Invoice", "Estimate", "SalesReceipt", "CreditMemo",
    "RefundReceipt", "Payment",
    # Purchases / A/P
    "Vendor", "Bill", "BillPayment", "VendorCredit", "PurchaseOrder",
    "Purchase",  # expenses / checks / cc charges
    # Banking / GL
    "Account", "Deposit", "Transfer", "JournalEntry",
    # Products & misc lists
    "Item", "Employee", "TimeActivity", "Class", "Department",
    "TaxCode", "TaxRate", "Term", "PaymentMethod", "Budget", "Attachable",
    "CompanyInfo", "Preferences",
]

# Common QBO reports (subset; any report name the API supports also works).
REPORTS = [
    "ProfitAndLoss", "ProfitAndLossDetail", "BalanceSheet", "CashFlow",
    "TrialBalance", "GeneralLedger", "TransactionList",
    "AgedReceivables", "AgedReceivableDetail",
    "AgedPayables", "AgedPayableDetail",
    "CustomerBalance", "CustomerBalanceDetail",
    "VendorBalance", "VendorBalanceDetail",
    "CustomerSales", "ItemSales", "VendorExpenses",
    "ClassSales", "DepartmentSales", "InventoryValuationSummary",
    "AccountListDetail",
]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Accept": "application/json",
    }


def _company_url(path: str) -> str:
    return f"{get_base_url()}/v3/company/{get_realm_id()}/{path}"


def _handle(resp: requests.Response) -> dict:
    if resp.status_code == 401:
        print("error: 401 Unauthorized — QBO token rejected (refresh failed). Reconnect QuickBooks in the NoDesk portal.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 403:
        print("error: 403 Forbidden — the connected QBO account lacks permission for that data.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 429:
        print("error: 429 Too Many Requests — QBO rate limit. Wait and retry.", file=sys.stderr)
        sys.exit(5)
    if resp.status_code >= 400:
        # QBO returns a Fault object with a human message
        try:
            fault = resp.json().get("Fault", {})
            errs = "; ".join(e.get("Message", "") + (f" ({e.get('Detail')})" if e.get("Detail") else "")
                             for e in fault.get("Error", []))
            print(f"error: QBO {resp.status_code}: {errs or resp.text[:300]}", file=sys.stderr)
        except ValueError:
            print(f"error: QBO {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def _query(sql: str) -> dict:
    resp = requests.get(
        _company_url("query"),
        headers=_headers(),
        params={"query": sql, "minorversion": MINOR_VERSION},
        timeout=TIMEOUT,
    )
    return _handle(resp)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v) if v is not None else ""


def _summarize_record(entity: str, r: dict) -> str:
    """One-line summary tuned per entity; falls back to Id + best-guess name."""
    rid = r.get("Id", "")
    name = (
        r.get("DisplayName")
        or r.get("Name")
        or r.get("FullyQualifiedName")
        or (r.get("CompanyName"))
        or ""
    )
    if entity in {"Invoice", "Estimate", "SalesReceipt", "CreditMemo", "RefundReceipt",
                  "Bill", "BillPayment", "VendorCredit", "PurchaseOrder", "Purchase", "Payment"}:
        who = (r.get("CustomerRef") or r.get("VendorRef") or r.get("EntityRef") or {}).get("name", "")
        doc = r.get("DocNumber", "")
        total = r.get("TotalAmt", r.get("Amount"))
        bal = r.get("Balance")
        date = r.get("TxnDate", "")
        extra = f"  balance={_fmt_money(bal)}" if bal not in (None, 0, "0", 0.0) else ""
        return f"- {rid}  #{doc:<8}  {date}  {who[:24]:<24}  {_fmt_money(total)}{extra}"
    if entity in {"Customer", "Vendor", "Employee"}:
        bal = r.get("Balance")
        contact = r.get("PrimaryEmailAddr", {}).get("Address", "") or (r.get("PrimaryPhone") or {}).get("FreeFormNumber", "")
        extra = f"  balance={_fmt_money(bal)}" if bal else ""
        return f"- {rid}  {name[:30]:<30}  {contact[:28]:<28}{extra}"
    if entity == "Item":
        price = r.get("UnitPrice")
        typ = r.get("Type", "")
        qty = r.get("QtyOnHand")
        q = f"  qty={qty}" if qty is not None else ""
        return f"- {rid}  {name[:30]:<30}  {typ:<10}  {_fmt_money(price)}{q}"
    if entity == "Account":
        return f"- {rid}  {name[:34]:<34}  {r.get('AccountType','')}/{r.get('AccountSubType','')}  {_fmt_money(r.get('CurrentBalance'))}"
    return f"- {rid}  {name}"


def _print_records(entity: str, records: list, as_json: bool) -> None:
    if as_json:
        print(json.dumps(records, indent=2))
        return
    if not records:
        print(f"No {entity} records found.")
        return
    for r in records:
        print(_summarize_record(entity, r))
    print(f"({len(records)} record(s))")


def _print_report(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
        return
    header = data.get("Header", {})
    title = header.get("ReportName", "Report")
    period = " ".join(filter(None, [header.get("StartPeriod", ""), "→", header.get("EndPeriod", "")])).strip("→ ")
    print(f"== {title} ==" + (f"  ({period})" if period.strip() else ""))
    cols = [c.get("ColTitle", "") for c in data.get("Columns", {}).get("Column", [])]
    if any(cols):
        print("  " + " | ".join(c for c in cols if c))

    def walk(rows, depth=0):
        for row in rows.get("Row", []):
            pad = "  " * (depth + 1)
            if "Header" in row:
                hcols = [c.get("value", "") for c in row["Header"].get("ColData", [])]
                label = next((c for c in hcols if c), "")
                if label:
                    print(f"{pad}{label}")
            if "ColData" in row:
                cells = [c.get("value", "") for c in row["ColData"]]
                label = cells[0] if cells else ""
                vals = "  ".join(v for v in cells[1:] if v)
                print(f"{pad}{label}" + (f"   {vals}" if vals else ""))
            if "Rows" in row:
                walk(row["Rows"], depth + 1)
            if "Summary" in row:
                cells = [c.get("value", "") for c in row["Summary"].get("ColData", [])]
                label = cells[0] if cells else ""
                vals = "  ".join(v for v in cells[1:] if v)
                print(f"{pad}{label or 'Total'}   {vals}")

    walk(data.get("Rows", {}))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_query(args) -> None:
    data = _query(args.sql)
    qr = data.get("QueryResponse", {})
    # The response keys the result list by entity name; grab the first list value.
    records = next((v for v in qr.values() if isinstance(v, list)), [])
    entity = next((k for k, v in qr.items() if isinstance(v, list)), "Record")
    _print_records(entity, records, args.json)


def cmd_list(args) -> None:
    entity = args.entity
    # Case-insensitive match against the known entity set (QBO is case-sensitive).
    match = next((e for e in ENTITIES if e.lower() == entity.lower()), None)
    if not match:
        print(f"error: unknown entity '{entity}'. Known: {', '.join(ENTITIES)}", file=sys.stderr)
        sys.exit(1)
    sql = f"SELECT * FROM {match}"
    if args.where:
        sql += f" WHERE {args.where}"
    sql += f" MAXRESULTS {max(1, min(args.limit, 1000))}"
    data = _query(sql)
    qr = data.get("QueryResponse", {})
    records = qr.get(match, [])
    _print_records(match, records, args.json)


def cmd_get(args) -> None:
    match = next((e for e in ENTITIES if e.lower() == args.entity.lower()), args.entity)
    resp = requests.get(
        _company_url(match.lower()) + f"/{args.id}",
        headers=_headers(),
        params={"minorversion": MINOR_VERSION},
        timeout=TIMEOUT,
    )
    data = _handle(resp)
    record = data.get(match) or next((v for v in data.values() if isinstance(v, dict)), data)
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(json.dumps(record, indent=2))  # single records are most useful in full


def cmd_report(args) -> None:
    name = next((r for r in REPORTS if r.lower() == args.name.lower()), args.name)
    params = {"minorversion": MINOR_VERSION}
    if args.from_date:
        params["start_date"] = args.from_date
    if args.to_date:
        params["end_date"] = args.to_date
    if args.customer:
        params["customer"] = args.customer
    if args.vendor:
        params["vendor"] = args.vendor
    for kv in args.param or []:
        if "=" in kv:
            k, v = kv.split("=", 1)
            params[k] = v
    resp = requests.get(_company_url(f"reports/{name}"), headers=_headers(), params=params, timeout=TIMEOUT)
    _print_report(_handle(resp), args.json)


def cmd_company(args) -> None:
    data = _query("SELECT * FROM CompanyInfo")
    info = (data.get("QueryResponse", {}).get("CompanyInfo") or [{}])[0]
    if args.json:
        print(json.dumps(info, indent=2))
        return
    print(f"Company  : {info.get('CompanyName', '')}")
    print(f"Legal    : {info.get('LegalName', '')}")
    addr = info.get("CompanyAddr", {})
    print(f"Address  : " + ", ".join(filter(None, [addr.get('Line1'), addr.get('City'), addr.get('CountrySubDivisionCode'), addr.get('PostalCode')])))
    print(f"Email    : {info.get('Email', {}).get('Address', '')}")
    print(f"Country  : {info.get('Country', '')}")
    print(f"FY start : {info.get('FiscalYearStartMonth', '')}")
    print(f"Realm/Env: {get_realm_id()} / {'production' if 'sandbox' not in get_base_url() else 'sandbox'}")


def main() -> int:
    p = argparse.ArgumentParser(description="QuickBooks Online — read-only lookups, queries, reports")
    p.add_argument("--json", action="store_true", help="raw JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("query", help="run any QBO SQL SELECT")
    q.add_argument("sql")

    ls = sub.add_parser("list", help="SELECT * FROM <Entity> [WHERE ...]")
    ls.add_argument("entity", help=f"one of: {', '.join(ENTITIES)}")
    ls.add_argument("--where", help="QBO WHERE clause, e.g. \"Balance > '0'\"")
    ls.add_argument("--search", help="convenience: fuzzy name match (DisplayName/Name LIKE %%term%%)")
    ls.add_argument("--limit", type=int, default=100)

    g = sub.add_parser("get", help="read a single record by Id")
    g.add_argument("entity")
    g.add_argument("id")

    r = sub.add_parser("report", help=f"run a report ({', '.join(REPORTS[:6])}, …)")
    r.add_argument("name")
    r.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    r.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    r.add_argument("--customer", help="filter by customer Id")
    r.add_argument("--vendor", help="filter by vendor Id")
    r.add_argument("--param", action="append", metavar="key=value", help="any extra report param (repeatable)")

    sub.add_parser("company", help="company info + connectivity check")

    args = p.parse_args()

    # --search sugar: rewrite into a WHERE LIKE on the entity's name column.
    if args.cmd == "list" and args.search and not args.where:
        col = "DisplayName" if args.entity.lower() in {"customer", "vendor", "employee"} else "Name"
        args.where = f"{col} LIKE '%{args.search}%'"

    try:
        {
            "query": cmd_query,
            "list": cmd_list,
            "get": cmd_get,
            "report": cmd_report,
            "company": cmd_company,
        }[args.cmd](args)
    except requests.HTTPError as exc:
        print(f"error: HTTP {exc.response.status_code}: {exc.response.text[:300]}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:  # qbo_auth raises these when tokens are missing
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
