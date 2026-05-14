#!/usr/bin/env python3
"""
Look up leads/jobs across all connected Podio apps.

Usage:
    python3 podio_lookup.py --search "Devin Burchett"
    python3 podio_lookup.py --search "+14059992900"
    python3 podio_lookup.py --list-recent
    python3 podio_lookup.py --list-recent --limit 20
    python3 podio_lookup.py --search "Devin" --json
    python3 podio_lookup.py --update-status 3303283090 "Invoice Sent"
"""

import argparse
import json
import os
import re
import sys

import requests

from podio_access import get_podio_access_token, load_hermes_env

PODIO_API = "https://api.podio.com"
TIMEOUT = 15


def _load_app_ids() -> list[int]:
    """Return all Podio app IDs from PODIO_APPS_JSON, falling back to PODIO_APP_ID."""
    load_hermes_env()
    raw = os.environ.get("PODIO_APPS_JSON", "").strip().strip("'\"")
    if raw and raw != "[]":
        try:
            apps = json.loads(raw)
            ids = [int(a["app_id"]) for a in apps if a.get("app_id")]
            if ids:
                return ids
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    single = int(os.environ.get("PODIO_APP_ID", "0") or "0")
    return [single] if single else []


APP_IDS = _load_app_ids()
APP_ID = APP_IDS[0] if APP_IDS else 0  # kept for backward compat

FIELDS = {
    "name": 276836610,
    "phone": 276836705,
    "email": 276836706,
    "job_description": 276836707,
    "date": 276836708,
    "invoice_status": 276921460,
}

STATUS_OPTIONS = {
    "New Lead": 1,
    "Quoted": 2,
    "Invoice Sent": 3,
    "Invoice Paid": 4,
    "Cancelled": 5,
}
STATUS_IDS_TO_TEXT = {v: k for k, v in STATUS_OPTIONS.items()}


def get_access_token() -> str:
    try:
        return get_podio_access_token()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


def _headers():
    return {
        "Authorization": f"OAuth2 {get_access_token()}",
        "Content-Type": "application/json",
    }


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return raw


def _extract_field_value(field: dict) -> str:
    field_type = field.get("type", "")
    values = field.get("values", [])
    if not values:
        return ""

    if field_type in ("text", "number"):
        return values[0].get("value", "")
    elif field_type == "phone":
        return values[0].get("value", "")
    elif field_type == "email":
        return values[0].get("value", "")
    elif field_type == "date":
        start = values[0].get("start", "")
        return start.split(" ")[0] if start else ""
    elif field_type == "category":
        return values[0].get("value", {}).get("text", "")
    else:
        v = values[0]
        return v.get("value", str(v)) if isinstance(v, dict) else str(v)


def _parse_item(item: dict) -> dict:
    result = {
        "item_id": item.get("item_id"),
        "app_id": item.get("app", {}).get("app_id"),
        "title": item.get("title", ""),
        "name": "",
        "phone": "",
        "email": "",
        "job_description": "",
        "date": "",
        "invoice_status": "",
        "link": item.get("link", ""),
    }

    field_id_to_key = {v: k for k, v in FIELDS.items()}

    for field in item.get("fields", []):
        fid = field.get("field_id")
        if fid in field_id_to_key:
            result[field_id_to_key[fid]] = _extract_field_value(field)

    return result


def _is_phone_query(query: str) -> bool:
    return bool(re.match(r"^[\+\d\(\)\-\s]{7,}$", query.strip()))


def _phone_variants(query: str) -> list[str]:
    """Generate phone number format variants for matching."""
    digits = re.sub(r"\D", "", query)
    variants = set()
    variants.add(digits)
    if len(digits) >= 10:
        last10 = digits[-10:]
        variants.add(last10)
        variants.add(f"1{last10}")
        variants.add(f"+1{last10}")
        variants.add(f"+{digits}")
    return list(variants)


def _fetch_all_items_from_app(app_id: int, limit: int = 100) -> list[dict]:
    all_items = []
    offset = 0
    batch_size = min(limit, 100)
    while offset < limit:
        resp = requests.post(
            f"{PODIO_API}/item/app/{app_id}/filter/",
            headers=_headers(),
            json={"sort_by": "created_on", "sort_desc": True, "limit": batch_size, "offset": offset},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            break
        items = resp.json().get("items", [])
        if not items:
            break
        all_items.extend(items)
        offset += batch_size
        if len(items) < batch_size:
            break
    return all_items


def _fetch_all_items(limit: int = 100) -> list[dict]:
    """Fetch items across all connected apps."""
    all_items = []
    for app_id in APP_IDS:
        all_items.extend(_fetch_all_items_from_app(app_id, limit=limit))
    return all_items


def search_items(query: str) -> list[dict]:
    """Search by name or phone across all connected apps."""
    results = []

    if _is_phone_query(query):
        variants = _phone_variants(query)
        items = _fetch_all_items(limit=200)
        for item in items:
            parsed = _parse_item(item)
            item_phone_digits = re.sub(r"\D", "", parsed["phone"])
            for v in variants:
                v_digits = re.sub(r"\D", "", v)
                if v_digits and item_phone_digits and (
                    item_phone_digits == v_digits
                    or item_phone_digits.endswith(v_digits)
                    or v_digits.endswith(item_phone_digits)
                ):
                    results.append(parsed)
                    break
    else:
        for app_id in APP_IDS:
            resp = requests.post(
                f"{PODIO_API}/item/app/{app_id}/filter/",
                headers=_headers(),
                json={
                    "filters": {str(FIELDS["name"]): query},
                    "limit": 20,
                    "sort_by": "created_on",
                    "sort_desc": True,
                },
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                results.extend(_parse_item(i) for i in resp.json().get("items", []))

            if not any(r.get("app_id") == app_id for r in results):
                resp = requests.post(
                    f"{PODIO_API}/search/app/{app_id}/",
                    headers=_headers(),
                    json={"query": query, "limit": 20, "ref_type": "item"},
                    timeout=TIMEOUT,
                )
                if resp.status_code == 200:
                    search_data = resp.json()
                    search_results = search_data if isinstance(search_data, list) else search_data.get("results", [])
                    item_ids = [r.get("id") for r in search_results if r.get("id")]
                    for iid in item_ids[:10]:
                        item_resp = requests.get(f"{PODIO_API}/item/{iid}", headers=_headers(), timeout=TIMEOUT)
                        if item_resp.status_code == 200:
                            results.append(_parse_item(item_resp.json()))

    seen = set()
    deduped = []
    for r in results:
        if r["item_id"] not in seen:
            seen.add(r["item_id"])
            deduped.append(r)
    return deduped


def list_recent(limit: int = 10) -> list[dict]:
    """List recent items across all connected apps."""
    all_items = []
    per_app = max(limit, limit * len(APP_IDS)) if len(APP_IDS) > 1 else limit
    for app_id in APP_IDS:
        resp = requests.post(
            f"{PODIO_API}/item/app/{app_id}/filter/",
            headers=_headers(),
            json={"sort_by": "created_on", "sort_desc": True, "limit": per_app},
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"Error listing items from app {app_id} ({resp.status_code}): {resp.text}", file=sys.stderr)
            continue
        all_items.extend(_parse_item(i) for i in resp.json().get("items", []))
    all_items.sort(key=lambda x: x.get("date") or "", reverse=True)
    return all_items[:limit]


def update_item_status(item_id: int, status_text: str) -> bool:
    """Set the Invoice Status category on a Podio item."""
    if status_text not in STATUS_OPTIONS:
        valid = ", ".join(STATUS_OPTIONS.keys())
        print(f"Error: Invalid status '{status_text}'. Valid options: {valid}", file=sys.stderr)
        return False

    option_id = STATUS_OPTIONS[status_text]
    resp = requests.put(
        f"{PODIO_API}/item/{item_id}/value/{FIELDS['invoice_status']}",
        headers=_headers(),
        json=option_id,
        timeout=TIMEOUT,
    )

    if resp.status_code in (200, 204):
        print(f"Updated item {item_id} -> Invoice Status: {status_text}")
        return True
    else:
        print(f"Failed to update status ({resp.status_code}): {resp.text}", file=sys.stderr)
        return False


def print_lead(lead: dict, index: int = None):
    prefix = f"[{index}] " if index is not None else ""
    status = lead.get("invoice_status") or "(not set)"
    print(f"{prefix}Name:     {lead['name'] or lead['title'] or '(unknown)'}")
    print(f"    Phone:    {lead['phone'] or '(none)'}")
    print(f"    Email:    {lead['email'] or '(none)'}")
    print(f"    Job:      {lead['job_description'] or '(none)'}")
    print(f"    Date:     {lead['date'] or '(none)'}")
    print(f"    Status:   {status}")
    print(f"    Item ID:  {lead['item_id']}")
    print(f"    App ID:   {lead.get('app_id') or '(unknown)'}")
    if lead.get("link"):
        print(f"    Link:     {lead['link']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Search configured Podio leads/jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", "-s", help="Search by customer name or phone number")
    parser.add_argument("--list-recent", "-l", action="store_true", help="List recent leads")
    parser.add_argument("--limit", type=int, default=10, help="Number of results (default 10)")
    parser.add_argument("--json", "-j", action="store_true", dest="output_json", help="Output raw JSON")
    parser.add_argument(
        "--update-status", nargs=2, metavar=("ITEM_ID", "STATUS"),
        help='Set invoice status on an item, e.g. --update-status 3303283090 "Invoice Sent"',
    )
    args = parser.parse_args()

    if not args.search and not args.list_recent and not args.update_status:
        parser.print_help()
        sys.exit(1)

    if args.update_status:
        item_id, status_text = args.update_status
        success = update_item_status(int(item_id), status_text)
        sys.exit(0 if success else 1)

    if args.list_recent:
        leads = list_recent(args.limit)
        if not leads:
            print("No leads found.")
            return
        if args.output_json:
            print(json.dumps(leads, indent=2))
        else:
            print(f"Recent leads ({len(leads)}):\n")
            for i, lead in enumerate(leads, 1):
                print_lead(lead, i)
        return

    if args.search:
        leads = search_items(args.search)
        if not leads:
            print(f"No leads found matching: {args.search}")
            return
        if args.output_json:
            print(json.dumps(leads, indent=2))
        else:
            print(f"Found {len(leads)} lead(s) matching '{args.search}':\n")
            for i, lead in enumerate(leads, 1):
                print_lead(lead, i)


if __name__ == "__main__":
    main()
