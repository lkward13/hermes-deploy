#!/usr/bin/env python3
"""
Read contacts, jobs, tasks, activities, estimates, and invoices from the
customer's JobNimbus account via the JobNimbus Public API (api1).

Read-only — this skill never writes to JobNimbus.

    python3 jobnimbus_lookup.py --account
    python3 jobnimbus_lookup.py --list-contacts [--limit 25]
    python3 jobnimbus_lookup.py --search "Smith"
    python3 jobnimbus_lookup.py --get-contact JNID
    python3 jobnimbus_lookup.py --list-jobs [--limit 25]
    python3 jobnimbus_lookup.py --get-job JNID
    python3 jobnimbus_lookup.py --list-tasks [--limit 25]
    python3 jobnimbus_lookup.py --list-activities [--limit 25]
    python3 jobnimbus_lookup.py --list-estimates [--limit 25]
    python3 jobnimbus_lookup.py --list-invoices [--limit 25]
    python3 jobnimbus_lookup.py --list-contacts --filter '{"must":[{"term":{"status_name":"Lead"}}]}'

All commands accept --json for raw JSON output.

Reads credentials from environment (populated by ~/.hermes/.env):
    JOBNIMBUS_API_KEY   required — generate in JobNimbus → Settings → API
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

BASE_URL = "https://app.jobnimbus.com/api1"
TIMEOUT = 25


def _api_key() -> str:
    key = os.environ.get("JOBNIMBUS_API_KEY", "").strip()
    if not key:
        print(
            "error: JOBNIMBUS_API_KEY not set. Connect JobNimbus in the NoDesk portal.",
            file=sys.stderr,
        )
        sys.exit(2)
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    resp = requests.request(method, url, headers=_headers(), params=params, timeout=TIMEOUT)
    if resp.status_code == 401:
        print("error: 401 Unauthorized — JobNimbus API key rejected. Reconnect in the NoDesk portal.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 403:
        print("error: 403 Forbidden — this API key lacks permission for that resource.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code == 404:
        print("error: 404 Not Found — check the JNID and that the record exists.", file=sys.stderr)
        sys.exit(4)
    if resp.status_code == 429:
        print("error: 429 Too Many Requests — JobNimbus rate limit hit. Wait a moment and retry.", file=sys.stderr)
        sys.exit(5)
    resp.raise_for_status()
    return resp.json()


def _epoch_to_date(val) -> str:
    """JobNimbus timestamps are Unix epoch seconds (0 / None when unset)."""
    if not val:
        return ""
    try:
        return datetime.fromtimestamp(int(val), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(val)


def _money(val) -> str:
    if val in (None, ""):
        return ""
    try:
        return f"${float(val):,.2f}"
    except (TypeError, ValueError):
        return str(val)


def _results(data: dict) -> list:
    """List endpoints return {count, results:[...]}; tolerate a bare list too."""
    if isinstance(data, list):
        return data
    return data.get("results", []) if isinstance(data, dict) else []


def _list_params(limit: int, raw_filter: str | None) -> dict:
    params: dict = {"size": limit, "from": 0}
    if raw_filter:
        try:
            json.loads(raw_filter)  # validate it's JSON before sending
        except json.JSONDecodeError:
            print("error: --filter must be valid JSON (JobNimbus ElasticSearch filter).", file=sys.stderr)
            sys.exit(1)
        params["filter"] = raw_filter
    return params


def _contact_name(c: dict) -> str:
    return (
        c.get("display_name")
        or " ".join(filter(None, [c.get("first_name"), c.get("last_name")]))
        or c.get("company")
        or "(unnamed)"
    )


def _contact_phone(c: dict) -> str:
    return c.get("mobile_phone") or c.get("home_phone") or c.get("work_phone") or ""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def account(as_json: bool) -> None:
    """Fetch account info — doubles as a connectivity / key-validity check."""
    data = _request("GET", "/account")
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Account : {data.get('name') or data.get('display_name') or '?'}")
    print(f"ID      : {data.get('jnid') or data.get('id') or ''}")
    print(f"Email   : {data.get('email', '')}")
    print("JobNimbus API key is valid.")


def list_contacts(limit: int, raw_filter: str | None, as_json: bool) -> None:
    data = _request("GET", "/contacts", params=_list_params(limit, raw_filter))
    rows = _results(data)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No contacts found.")
        return
    for c in rows:
        print(f"- {c.get('jnid', '')}  {_contact_name(c):<28}  {_contact_phone(c):<14}  {c.get('email', ''):<26}  status={c.get('status_name', '')}")


def search_contacts(query: str, limit: int, as_json: bool) -> None:
    """Client-side substring match over name / email / phone / company."""
    data = _request("GET", "/contacts", params={"size": max(limit, 200), "from": 0})
    needle = query.strip().lower()
    digits = "".join(ch for ch in query if ch.isdigit())
    matches = []
    for c in _results(data):
        haystack = " ".join(filter(None, [
            _contact_name(c), c.get("email", ""), c.get("company", ""),
        ])).lower()
        hit = needle in haystack
        if not hit and digits:
            phone_digits = "".join(ch for ch in _contact_phone(c) if ch.isdigit())
            hit = digits in phone_digits
        if hit:
            matches.append(c)
    if as_json:
        print(json.dumps(matches, indent=2))
        return
    if not matches:
        print(f"No contacts matched '{query}'.")
        return
    for c in matches:
        print(f"- {c.get('jnid', '')}  {_contact_name(c):<28}  {_contact_phone(c):<14}  {c.get('email', ''):<26}  status={c.get('status_name', '')}")


def get_contact(jnid: str, as_json: bool) -> None:
    data = _request("GET", f"/contacts/{jnid}")
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Contact  : {_contact_name(data)}")
    print(f"JNID     : {data.get('jnid', '')}")
    print(f"Phone    : {_contact_phone(data)}")
    print(f"Email    : {data.get('email', '')}")
    print(f"Company  : {data.get('company', '')}")
    addr = ", ".join(filter(None, [data.get("address_line1"), data.get("city"), data.get("state_text"), data.get("zip")]))
    if addr:
        print(f"Address  : {addr}")
    print(f"Status   : {data.get('status_name', '')}")
    print(f"Type     : {data.get('record_type_name', '')}")
    print(f"Created  : {_epoch_to_date(data.get('date_created'))}")


def list_jobs(limit: int, raw_filter: str | None, as_json: bool) -> None:
    data = _request("GET", "/jobs", params=_list_params(limit, raw_filter))
    rows = _results(data)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No jobs found.")
        return
    for j in rows:
        name = j.get("name") or j.get("display_name") or f"#{j.get('number', '')}"
        print(f"- {j.get('jnid', '')}  {name:<30}  status={j.get('status_name', ''):<16}  type={j.get('record_type_name', '')}  created={_epoch_to_date(j.get('date_created'))}")


def get_job(jnid: str, as_json: bool) -> None:
    data = _request("GET", f"/jobs/{jnid}")
    if as_json:
        print(json.dumps(data, indent=2))
        return
    print(f"Job      : {data.get('name') or data.get('display_name') or '#' + str(data.get('number', ''))}")
    print(f"JNID     : {data.get('jnid', '')}")
    print(f"Number   : {data.get('number', '')}")
    print(f"Status   : {data.get('status_name', '')}")
    print(f"Type     : {data.get('record_type_name', '')}")
    addr = ", ".join(filter(None, [data.get("address_line1"), data.get("city"), data.get("state_text"), data.get("zip")]))
    if addr:
        print(f"Address  : {addr}")
    print(f"Sales rep: {data.get('sales_rep_name', '')}")
    print(f"Created  : {_epoch_to_date(data.get('date_created'))}")


def list_tasks(limit: int, raw_filter: str | None, as_json: bool) -> None:
    data = _request("GET", "/tasks", params=_list_params(limit, raw_filter))
    rows = _results(data)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No tasks found.")
        return
    for t in rows:
        done = "✓" if t.get("is_completed") else " "
        title = t.get("title") or t.get("record_type_name") or "(untitled)"
        print(f"- [{done}] {t.get('jnid', '')}  {title:<32}  due={_epoch_to_date(t.get('date_end') or t.get('date_start'))}  priority={t.get('priority', '')}")


def list_activities(limit: int, raw_filter: str | None, as_json: bool) -> None:
    data = _request("GET", "/activities", params=_list_params(limit, raw_filter))
    rows = _results(data)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No activities found.")
        return
    for a in rows:
        note = (a.get("note") or a.get("record_type_name") or "").replace("\n", " ")
        print(f"- {_epoch_to_date(a.get('date_created'))}  {a.get('created_by_name', ''):<18}  {note[:80]}")


def list_estimates(limit: int, raw_filter: str | None, as_json: bool) -> None:
    _list_financial("/estimates", "estimates", limit, raw_filter, as_json)


def list_invoices(limit: int, raw_filter: str | None, as_json: bool) -> None:
    _list_financial("/invoices", "invoices", limit, raw_filter, as_json)


def _list_financial(path: str, label: str, limit: int, raw_filter: str | None, as_json: bool) -> None:
    data = _request("GET", path, params=_list_params(limit, raw_filter))
    rows = _results(data)
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print(f"No {label} found.")
        return
    for r in rows:
        print(f"- {r.get('jnid', '')}  #{r.get('number', ''):<10}  {_money(r.get('total')):<12}  status={r.get('status_name', ''):<14}  created={_epoch_to_date(r.get('date_created'))}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="JobNimbus — read-only lookups via the Public API")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--account", action="store_true", help="Account info / API-key connectivity check")
    g.add_argument("--list-contacts", action="store_true")
    g.add_argument("--search", metavar="QUERY", help="Search contacts by name, email, phone, or company")
    g.add_argument("--get-contact", metavar="JNID")
    g.add_argument("--list-jobs", action="store_true")
    g.add_argument("--get-job", metavar="JNID")
    g.add_argument("--list-tasks", action="store_true")
    g.add_argument("--list-activities", action="store_true")
    g.add_argument("--list-estimates", action="store_true")
    g.add_argument("--list-invoices", action="store_true")

    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--filter", dest="raw_filter", metavar="JSON",
                        help='Raw JobNimbus ElasticSearch filter, e.g. \'{"must":[{"term":{"status_name":"Lead"}}]}\'')

    args = parser.parse_args()
    limit = max(1, min(args.limit, 1000))

    try:
        if args.account:
            account(args.json)
        elif args.list_contacts:
            list_contacts(limit, args.raw_filter, args.json)
        elif args.search:
            search_contacts(args.search, limit, args.json)
        elif args.get_contact:
            get_contact(args.get_contact, args.json)
        elif args.list_jobs:
            list_jobs(limit, args.raw_filter, args.json)
        elif args.get_job:
            get_job(args.get_job, args.json)
        elif args.list_tasks:
            list_tasks(limit, args.raw_filter, args.json)
        elif args.list_activities:
            list_activities(limit, args.raw_filter, args.json)
        elif args.list_estimates:
            list_estimates(limit, args.raw_filter, args.json)
        elif args.list_invoices:
            list_invoices(limit, args.raw_filter, args.json)
    except requests.HTTPError as exc:
        print(f"error: HTTP {exc.response.status_code}: {exc.response.text[:500]}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
