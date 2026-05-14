#!/usr/bin/env python3
"""
Look up leads/jobs in the configured Podio app.

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
import time
from pathlib import Path

import requests

PODIO_API = "https://api.podio.com"
TIMEOUT = 15

# Set PODIO_APP_ID for each client if this skill is enabled.
APP_ID = int(os.environ.get("PODIO_APP_ID", "0") or "0")

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

_token_cache = {"access_token": None, "expires_at": 0}


def _load_env():
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        print(f"Error: {env_path} not found", file=sys.stderr)
        sys.exit(1)

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _get_creds():
    _load_env()
    required = ["PODIO_CLIENT_ID", "PODIO_CLIENT_SECRET", "PODIO_USERNAME", "PODIO_PASSWORD"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Error: Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return {k: os.environ[k] for k in required}


def get_access_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] - now > 60:
        return _token_cache["access_token"]

    _load_env()
    oauth_token = os.environ.get("PODIO_ACCESS_TOKEN", "").strip().strip("'\"")
    if oauth_token:
        _token_cache["access_token"] = oauth_token
        _token_cache["expires_at"] = now + 3600
        return oauth_token

    creds = _get_creds()
    resp = requests.post(
        "https://podio.com/oauth/token",
        data={
            "grant_type": "password",
            "client_id": creds["PODIO_CLIENT_ID"],
            "client_secret": creds["PODIO_CLIENT_SECRET"],
            "username": creds["PODIO_USERNAME"],
            "password": creds["PODIO_PASSWORD"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )

    if resp.status_code != 200:
        print(f"Auth failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return data["access_token"]


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


def _fetch_all_items(limit: int = 100) -> list[dict]:
    """Fetch items from the app (paginated if needed) for client-side filtering."""
    all_items = []
    offset = 0
    batch_size = min(limit, 100)

    while offset < limit:
        resp = requests.post(
            f"{PODIO_API}/item/app/{APP_ID}/filter/",
            headers=_headers(),
            json={
                "sort_by": "created_on",
                "sort_desc": True,
                "limit": batch_size,
                "offset": offset,
            },
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


def search_items(query: str) -> list[dict]:
    """Search by name or phone."""
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
        resp = requests.post(
            f"{PODIO_API}/item/app/{APP_ID}/filter/",
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
            items = resp.json().get("items", [])
            results.extend(_parse_item(i) for i in items)

        if not results:
            resp = requests.post(
                f"{PODIO_API}/search/app/{APP_ID}/",
                headers=_headers(),
                json={"query": query, "limit": 20, "ref_type": "item"},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                search_data = resp.json()
                search_results = search_data if isinstance(search_data, list) else search_data.get("results", [])
                item_ids = [r.get("id") for r in search_results if r.get("id")]
                for iid in item_ids[:10]:
                    item_resp = requests.get(
                        f"{PODIO_API}/item/{iid}",
                        headers=_headers(),
                        timeout=TIMEOUT,
                    )
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
    resp = requests.post(
        f"{PODIO_API}/item/app/{APP_ID}/filter/",
        headers=_headers(),
        json={
            "sort_by": "created_on",
            "sort_desc": True,
            "limit": limit,
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        print(f"Error listing items ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []
    items = resp.json().get("items", [])
    return [_parse_item(i) for i in items]


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
