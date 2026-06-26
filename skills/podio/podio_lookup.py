#!/usr/bin/env python3
"""
Read from Podio: any app's items, a single item in full, and the apps
available in the workspace/org.

The default app (PODIO_APP_ID) is the leads/jobs app, but --app targets any
app so the agent can read across the whole Podio account.

Usage:
    python3 podio_lookup.py --search "Devin Burchett"
    python3 podio_lookup.py --search "+14059992900"
    python3 podio_lookup.py --list-recent
    python3 podio_lookup.py --list-recent --limit 20
    python3 podio_lookup.py --search "Devin" --json
    python3 podio_lookup.py --update-status 3303283090 "Invoice Sent"

    # Any-app reads (override the default leads app)
    python3 podio_lookup.py --app 12345678 --list-recent
    python3 podio_lookup.py --app 12345678 --search "Acme"

    # Read one item fully (all fields, comments count, link)
    python3 podio_lookup.py --get-item 3303283090

    # Discover app IDs in the workspace / org
    python3 podio_lookup.py --list-apps
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
APP_ID = int(os.environ.get("PODIO_APP_ID", "30724222") or "30724222")

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
            value = value.strip().strip("'\"")
            os.environ.setdefault(key.strip(), value)


def _get_creds():
    _load_env()
    required = ["PODIO_CLIENT_ID", "PODIO_CLIENT_SECRET", "PODIO_USERNAME", "PODIO_PASSWORD"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Error: Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return {k: os.environ[k] for k in required}


def _refresh_oauth_token() -> str:
    """Refresh the Podio OAuth access token using the refresh token."""
    _load_env()
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
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        return ""
    data = resp.json()
    new_token = data.get("access_token", "")
    if new_token:
        # Update env file so next call uses the fresh token
        env_path = Path.home() / ".hermes" / ".env"
        if env_path.exists():
            content = env_path.read_text()
            content = re.sub(
                r"^(PODIO_ACCESS_TOKEN=)['\"]?[^'\"\n]*['\"]?",
                f"PODIO_ACCESS_TOKEN='{new_token}'",
                content,
                flags=re.MULTILINE,
            )
            env_path.write_text(content)
        os.environ["PODIO_ACCESS_TOKEN"] = new_token
        _token_cache["access_token"] = new_token
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 28800)
    return new_token


def get_access_token() -> str:
    _load_env()
    # Use OAuth token from env if available (set via NoDesk portal OAuth flow)
    oauth_token = os.environ.get("PODIO_ACCESS_TOKEN", "")
    if oauth_token:
        return oauth_token

    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] - now > 60:
        return _token_cache["access_token"]

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


def _headers(token: str | None = None):
    return {
        "Authorization": f"OAuth2 {token or get_access_token()}",
        "Content-Type": "application/json",
    }


def _api_post(url: str, payload: dict) -> dict:
    """POST to Podio API with automatic token refresh on 401."""
    resp = requests.post(url, json=payload, headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 401:
        new_token = _refresh_oauth_token()
        if new_token:
            resp = requests.post(url, json=payload, headers=_headers(new_token), timeout=TIMEOUT)
    return resp


def _api_put(url: str, payload) -> dict:
    """PUT to Podio API with automatic token refresh on 401."""
    resp = requests.put(url, json=payload, headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 401:
        new_token = _refresh_oauth_token()
        if new_token:
            resp = requests.put(url, json=payload, headers=_headers(new_token), timeout=TIMEOUT)
    return resp


def _api_get(url: str, params: dict | None = None) -> dict:
    """GET from Podio API with automatic token refresh on 401."""
    resp = requests.get(url, params=params, headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 401:
        new_token = _refresh_oauth_token()
        if new_token:
            resp = requests.get(url, params=params, headers=_headers(new_token), timeout=TIMEOUT)
    return resp


def _api_delete(url: str) -> dict:
    """DELETE to Podio API with automatic token refresh on 401."""
    resp = requests.delete(url, headers=_headers(), timeout=TIMEOUT)
    if resp.status_code == 401:
        new_token = _refresh_oauth_token()
        if new_token:
            resp = requests.delete(url, headers=_headers(new_token), timeout=TIMEOUT)
    return resp


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
        # The item's real creation timestamp (Podio top-level created_on, a full
        # "YYYY-MM-DD HH:MM:SS" in UTC). The "date" field above is a custom app
        # field (often date-only), so anything that needs true lead age must use
        # created_on, not date.
        "created_on": item.get("created_on", ""),
        "invoice_status": "",
        "link": item.get("link", ""),
    }

    field_id_to_key = {v: k for k, v in FIELDS.items()}

    for field in item.get("fields", []):
        fid = field.get("field_id")
        if fid in field_id_to_key:
            result[field_id_to_key[fid]] = _extract_field_value(field)

    return result


def _parse_item_generic(item: dict) -> dict:
    """Schema-agnostic parse: extract every field by its external_id + label.

    Used for any app other than the configured leads app, where the FIELDS map
    does not apply.
    """
    fields = []
    for field in item.get("fields", []):
        fields.append({
            "field_id": field.get("field_id"),
            "external_id": field.get("external_id", ""),
            "label": field.get("label", ""),
            "type": field.get("type", ""),
            "value": _extract_field_value(field),
        })
    return {
        "item_id": item.get("item_id"),
        "title": item.get("title", ""),
        "app": (item.get("app") or {}).get("name", ""),
        "app_id": (item.get("app") or {}).get("app_id"),
        "fields": fields,
        "comments": item.get("comment_count", len(item.get("comments", []))),
        "link": item.get("link", ""),
    }


def get_item(item_id: int) -> dict | None:
    """Read a single item fully, regardless of which app it belongs to."""
    resp = _api_get(f"{PODIO_API}/item/{item_id}")
    if resp.status_code != 200:
        print(f"Error reading item {item_id} ({resp.status_code}): {resp.text}", file=sys.stderr)
        return None
    return _parse_item_generic(resp.json())


def list_apps() -> list[dict]:
    """List apps the authenticated user can see, grouped for app-ID discovery."""
    resp = _api_get(f"{PODIO_API}/app/")
    if resp.status_code != 200:
        print(f"Error listing apps ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []
    apps = []
    for app in resp.json():
        cfg = app.get("config", {}) or {}
        space = app.get("space", {}) or {}
        apps.append({
            "app_id": app.get("app_id"),
            "name": cfg.get("name") or app.get("name", ""),
            "item_name": cfg.get("item_name", ""),
            "space": space.get("name", ""),
            "space_id": app.get("space_id") or space.get("space_id"),
            "status": app.get("status", ""),
            "link": app.get("link", ""),
        })
    return apps


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


def _fetch_all_items(limit: int = 100, app_id: int | None = None) -> list[dict]:
    """Fetch items from the app (paginated if needed) for client-side filtering."""
    app_id = app_id or APP_ID
    all_items = []
    offset = 0
    batch_size = min(limit, 100)

    while offset < limit:
        resp = _api_post(
            f"{PODIO_API}/item/app/{app_id}/filter/",
            {
                "sort_by": "created_on",
                "sort_desc": True,
                "limit": batch_size,
                "offset": offset,
            },
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


def search_items(query: str, app_id: int | None = None) -> list[dict]:
    """Search by name or phone (default leads app) or by text (any app)."""
    app_id = app_id or APP_ID
    is_default_app = app_id == APP_ID
    parse = _parse_item if is_default_app else _parse_item_generic
    results = []

    if _is_phone_query(query):
        variants = _phone_variants(query)
        items = _fetch_all_items(limit=200, app_id=app_id)
        for item in items:
            parsed = parse(item)
            item_phone_digits = re.sub(r"\D", "", _item_phone(parsed))
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
        # The field-id name filter only exists in the known leads app schema.
        if is_default_app:
            resp = _api_post(
                f"{PODIO_API}/item/app/{app_id}/filter/",
                {
                    "filters": {str(FIELDS["name"]): query},
                    "limit": 20,
                    "sort_by": "created_on",
                    "sort_desc": True,
                },
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                results.extend(parse(i) for i in items)

        if not results:
            resp = _api_post(
                f"{PODIO_API}/search/app/{app_id}/",
                {"query": query, "limit": 20, "ref_type": "item"},
            )
            if resp.status_code == 200:
                search_data = resp.json()
                search_results = search_data if isinstance(search_data, list) else search_data.get("results", [])
                item_ids = [r.get("id") for r in search_results if r.get("id")]
                for iid in item_ids[:10]:
                    item_resp = _api_get(f"{PODIO_API}/item/{iid}")
                    if item_resp.status_code == 200:
                        results.append(parse(item_resp.json()))

    seen = set()
    deduped = []
    for r in results:
        if r["item_id"] not in seen:
            seen.add(r["item_id"])
            deduped.append(r)
    return deduped


def _item_phone(parsed: dict) -> str:
    """Pull a phone value out of either a leads-parsed or generic-parsed item."""
    if parsed.get("phone"):
        return parsed["phone"]
    for f in parsed.get("fields", []):
        if f.get("type") == "phone":
            return f.get("value", "")
    return ""


def list_recent(limit: int = 10, app_id: int | None = None) -> list[dict]:
    app_id = app_id or APP_ID
    parse = _parse_item if app_id == APP_ID else _parse_item_generic
    resp = _api_post(
        f"{PODIO_API}/item/app/{app_id}/filter/",
        {
            "sort_by": "created_on",
            "sort_desc": True,
            "limit": limit,
        },
    )
    if resp.status_code != 200:
        print(f"Error listing items ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []
    items = resp.json().get("items", [])
    return [parse(i) for i in items]


def update_item_status(item_id: int, status_text: str) -> bool:
    """Set the Invoice Status category on a Podio item."""
    if status_text not in STATUS_OPTIONS:
        valid = ", ".join(STATUS_OPTIONS.keys())
        print(f"Error: Invalid status '{status_text}'. Valid options: {valid}", file=sys.stderr)
        return False

    option_id = STATUS_OPTIONS[status_text]
    resp = _api_put(
        f"{PODIO_API}/item/{item_id}/value/{FIELDS['invoice_status']}",
        option_id,
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


def print_generic_item(item: dict, index: int = None):
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}{item.get('title') or '(untitled)'}")
    if item.get("app"):
        print(f"    App:      {item['app']}" + (f" ({item['app_id']})" if item.get('app_id') else ""))
    for f in item.get("fields", []):
        label = f.get("label") or f.get("external_id") or f.get("field_id")
        val = f.get("value")
        if val in (None, "", []):
            continue
        print(f"    {label}: {val}")
    if item.get("comments"):
        print(f"    Comments: {item['comments']}")
    print(f"    Item ID:  {item.get('item_id')}")
    if item.get("link"):
        print(f"    Link:     {item['link']}")
    print()


def print_app(app: dict, index: int = None):
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}{app.get('name') or '(unnamed app)'}  (app_id {app.get('app_id')})")
    if app.get("space"):
        print(f"    Space:    {app['space']}" + (f" ({app['space_id']})" if app.get('space_id') else ""))
    if app.get("item_name"):
        print(f"    Items:    {app['item_name']}")
    if app.get("status"):
        print(f"    Status:   {app['status']}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Search configured Podio leads/jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search", "-s", help="Search by customer name or phone number")
    parser.add_argument("--list-recent", "-l", action="store_true", help="List recent items")
    parser.add_argument("--get-item", "-g", metavar="ITEM_ID", help="Read a single item fully")
    parser.add_argument("--list-apps", action="store_true", help="List apps available in the workspace/org")
    parser.add_argument(
        "--app", "-a", type=int, metavar="APP_ID",
        help="Target any app by ID (defaults to PODIO_APP_ID, the leads/jobs app)",
    )
    parser.add_argument("--limit", type=int, default=10, help="Number of results (default 10)")
    parser.add_argument("--json", "-j", action="store_true", dest="output_json", help="Output raw JSON")
    parser.add_argument(
        "--update-status", nargs=2, metavar=("ITEM_ID", "STATUS"),
        help='Set invoice status on an item, e.g. --update-status 3303283090 "Invoice Sent"',
    )
    args = parser.parse_args()

    if not (args.search or args.list_recent or args.update_status
            or args.get_item or args.list_apps):
        parser.print_help()
        sys.exit(1)

    # Whether we are reading the configured leads app or an arbitrary one.
    target_app = args.app or APP_ID
    is_default_app = target_app == APP_ID

    if args.list_apps:
        apps = list_apps()
        if not apps:
            print("No apps found.")
            return
        if args.output_json:
            print(json.dumps(apps, indent=2))
        else:
            print(f"Apps ({len(apps)}):\n")
            for i, app in enumerate(apps, 1):
                print_app(app, i)
        return

    if args.get_item:
        item = get_item(int(args.get_item))
        if not item:
            sys.exit(1)
        if args.output_json:
            print(json.dumps(item, indent=2))
        else:
            print_generic_item(item)
        return

    if args.update_status:
        item_id, status_text = args.update_status
        success = update_item_status(int(item_id), status_text)
        sys.exit(0 if success else 1)

    if args.list_recent:
        leads = list_recent(args.limit, app_id=target_app)
        if not leads:
            print("No items found.")
            return
        if args.output_json:
            print(json.dumps(leads, indent=2))
        elif is_default_app:
            print(f"Recent leads ({len(leads)}):\n")
            for i, lead in enumerate(leads, 1):
                print_lead(lead, i)
        else:
            print(f"Recent items in app {target_app} ({len(leads)}):\n")
            for i, item in enumerate(leads, 1):
                print_generic_item(item, i)
        return

    if args.search:
        leads = search_items(args.search, app_id=target_app)
        if not leads:
            print(f"No items found matching: {args.search}")
            return
        if args.output_json:
            print(json.dumps(leads, indent=2))
        elif is_default_app:
            print(f"Found {len(leads)} lead(s) matching '{args.search}':\n")
            for i, lead in enumerate(leads, 1):
                print_lead(lead, i)
        else:
            print(f"Found {len(leads)} item(s) matching '{args.search}':\n")
            for i, item in enumerate(leads, 1):
                print_generic_item(item, i)


if __name__ == "__main__":
    main()
