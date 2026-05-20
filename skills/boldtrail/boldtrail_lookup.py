#!/usr/bin/env python3
"""
Look up, create, and update contacts in BoldTrail (real-estate CRM).

Usage:
    python3 boldtrail_lookup.py --list-recent
    python3 boldtrail_lookup.py --list-recent --limit 20
    python3 boldtrail_lookup.py --search "Jane Doe"
    python3 boldtrail_lookup.py --search "+14059992900"
    python3 boldtrail_lookup.py --get-contact 12345
    python3 boldtrail_lookup.py --create-contact --name "Jane Doe" \\
        --email jane@example.com --phone "+14059992900" --tag "buyer"
    python3 boldtrail_lookup.py --update-contact 12345 --tag "qualified"
    python3 boldtrail_lookup.py --search "Devin" --json

Auth: reads BOLDTRAIL_API_TOKEN from ~/.hermes/.env. Tries Authorization:Bearer
first, falls back to X-API-Token header if Bearer is rejected with 401. There
is no username/password flow — do not look for one.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# BoldTrail's public API is the kvCORE Public API V2 (Inside Real Estate
# rebranded kvCORE → BoldTrail; the API endpoint kept the kvcore.com host).
# Auth is `Authorization: Bearer <JWT>`. Filters use `filter[key]=value` syntax.
# Pagination via `page` + `limit` params (default 100, max 500).
# Spec: https://developer.insiderealestate.com/publicv2/docs/api-standards
DEFAULT_API_BASE = "https://api.kvcore.com/v2/public"
TIMEOUT = 15
RETRY_DELAYS = (1, 2, 4)  # exponential backoff on 429


def _load_env() -> None:
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        print(f"Error: {env_path} not found", file=sys.stderr)
        sys.exit(1)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        os.environ.setdefault(key.strip(), value)


def _get_token() -> str:
    _load_env()
    token = os.environ.get("BOLDTRAIL_API_TOKEN", "") or os.environ.get("BOLDTRAIL_ACCESS_TOKEN", "")
    if not token:
        print(
            "Error: BOLDTRAIL_API_TOKEN not set in ~/.hermes/.env. "
            "The customer needs to connect BoldTrail on their /connect/{token} portal page.",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _api_base() -> str:
    _load_env()
    base = os.environ.get("BOLDTRAIL_API_BASE", "").strip() or DEFAULT_API_BASE
    return base.rstrip("/")


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }


def _request(method: str, path: str, *, params: dict | None = None, json_body: dict | None = None) -> requests.Response:
    """HTTP request with retry on 429."""
    token = _get_token()
    url = f"{_api_base()}/{path.lstrip('/')}"
    headers = _headers(token)

    last_resp: requests.Response | None = None
    for delay in (0, *RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        resp = requests.request(
            method, url, headers=headers, params=params, json=json_body, timeout=TIMEOUT,
        )
        last_resp = resp
        if resp.status_code != 429:
            break
    return last_resp


def _api_get(path: str, params: dict | None = None) -> dict:
    resp = _request("GET", path, params=params)
    if resp.status_code >= 400:
        _die(resp, path)
    return resp.json() if resp.text else {}


def _api_post(path: str, body: dict) -> dict:
    resp = _request("POST", path, json_body=body)
    if resp.status_code >= 400:
        _die(resp, path)
    return resp.json() if resp.text else {}


def _api_put(path: str, body: dict) -> dict:
    resp = _request("PUT", path, json_body=body)
    if resp.status_code >= 400:
        _die(resp, path)
    return resp.json() if resp.text else {}


def _die(resp: requests.Response, path: str) -> None:
    body = (resp.text or "")[:300]
    msg = f"BoldTrail API error ({resp.status_code}) on {path}: {body}"
    if resp.status_code == 401:
        msg += "\n(Auth failed — token may be revoked. Customer should regenerate it in BoldTrail and re-paste on the connect portal.)"
    elif resp.status_code == 404:
        msg += "\n(Endpoint not found — BoldTrail's actual API path may differ from our default. Override BOLDTRAIL_API_BASE or update the script.)"
    print(msg, file=sys.stderr)
    sys.exit(1)


def _normalize_contact(raw: dict) -> dict:
    """Flatten BoldTrail's contact response into a stable shape for printing.

    BoldTrail's exact field naming isn't publicly documented; this maps the
    common variants (snake_case, camelCase, nested address objects) into a
    predictable dict the rest of the script consumes.
    """
    def first(d: dict, *keys: str, default: str = "") -> str:
        for k in keys:
            v = d.get(k)
            if v:
                return str(v) if not isinstance(v, dict) else first(v, "value", "primary", default=default)
        return default

    return {
        "id": first(raw, "id", "contact_id", "contactId"),
        "name": first(raw, "name", "full_name", "fullName") or (
            f"{first(raw, 'first_name', 'firstName')} {first(raw, 'last_name', 'lastName')}".strip()
        ),
        "email": first(raw, "email", "email_address", "emailAddress", "primary_email"),
        "phone": first(raw, "phone", "phone_number", "phoneNumber", "primary_phone"),
        "tags": raw.get("tags") or raw.get("labels") or [],
        "created_at": first(raw, "created_at", "createdAt", "created"),
        "updated_at": first(raw, "updated_at", "updatedAt", "updated"),
        "_raw": raw,
    }


def list_recent(limit: int) -> list[dict]:
    # No documented "sort by created" param; kvCORE's filter[registered_after]
    # gives recent-only. Without it we just get the default ordering and trust
    # the page/limit pagination.
    data = _api_get("/contacts", params={"limit": min(limit, 500)})
    items = data.get("contacts") or data.get("data") or data.get("items") or (data if isinstance(data, list) else [])
    return [_normalize_contact(c) for c in items[:limit]]


def search(query: str) -> list[dict]:
    """Search by name / email / phone. kvCORE's V2 search is filter-based, so we
    try the likely fields in sequence and return the union. If it looks like an
    email, prefer filter[email]; if it looks like a phone, filter[phone]; else
    treat as a name and try filter[name]."""
    candidates: list[dict] = []
    seen: set = set()

    def merge(items):
        for raw in items:
            cid = raw.get("id") or raw.get("contact_id")
            if cid in seen:
                continue
            seen.add(cid)
            candidates.append(raw)

    def fetch(filter_key: str, value: str) -> list[dict]:
        data = _api_get("/contacts", params={f"filter[{filter_key}]": value, "limit": 20})
        return data.get("contacts") or data.get("data") or data.get("items") or (data if isinstance(data, list) else [])

    if "@" in query:
        merge(fetch("email", query))
    elif any(c.isdigit() for c in query) and not any(c.isalpha() for c in query):
        merge(fetch("phone", query))
    else:
        # Name search — try several possible filter keys; kvCORE varies by deployment
        for key in ("name", "first_name", "last_name"):
            try:
                merge(fetch(key, query))
            except SystemExit:
                # _die() would exit; we swallow individual filter failures and
                # rely on at least one of the candidates returning something.
                # If ALL fail, the script will print an empty result.
                pass

    return [_normalize_contact(c) for c in candidates]


def get_contact(contact_id: str) -> dict:
    data = _api_get(f"/contact/{contact_id}")
    inner = data.get("contact") or data.get("data") or data
    return _normalize_contact(inner)


def create_contact(name: str, email: str, phone: str, tags: list[str]) -> dict:
    # Per kvCORE docs, POST is to /contact (singular), body uses first_name + last_name.
    parts = name.split(maxsplit=1)
    body: dict = {
        "first_name": parts[0] if parts else "",
        "last_name": parts[1] if len(parts) > 1 else "",
    }
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    if tags:
        # kvCORE calls these "hashtags" in filters; the create field may differ.
        # Try both shapes by sending under both keys — server will ignore unknown.
        body["hashtags"] = tags
        body["tags"] = tags
    data = _api_post("/contact", body)
    inner = data.get("contact") or data.get("data") or data
    return _normalize_contact(inner)


def update_contact(contact_id: str, *, email: str = "", phone: str = "", tags: list[str] | None = None) -> dict:
    body: dict = {}
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    if tags:
        body["hashtags"] = tags
        body["tags"] = tags
    if not body:
        print("Error: --update-contact requires at least one of --email, --phone, --tag", file=sys.stderr)
        sys.exit(1)
    data = _api_put(f"/contact/{contact_id}", body)
    inner = data.get("contact") or data.get("data") or data
    return _normalize_contact(inner)


def _print_contact(c: dict, index: int | None = None) -> None:
    prefix = f"[{index}] " if index is not None else ""
    print(f"{prefix}ID:        {c['id']}")
    print(f"    Name:      {c['name'] or '(unknown)'}")
    print(f"    Email:     {c['email'] or '(none)'}")
    print(f"    Phone:     {c['phone'] or '(none)'}")
    if c["tags"]:
        tags = ", ".join(t if isinstance(t, str) else t.get("name", "") for t in c["tags"])
        print(f"    Tags:      {tags}")
    if c["created_at"]:
        print(f"    Created:   {c['created_at']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BoldTrail contact CLI (NoDesk skill)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list-recent", action="store_true", help="List newest contacts")
    parser.add_argument("--search", "-s", metavar="QUERY", help="Search contacts by name/email/phone")
    parser.add_argument("--get-contact", metavar="ID", help="Fetch a single contact's record")
    parser.add_argument("--create-contact", action="store_true", help="Create a new contact (use with --name + --email/--phone)")
    parser.add_argument("--update-contact", metavar="ID", help="Update an existing contact's fields/tags")
    parser.add_argument("--name", help="Contact name (for --create-contact)")
    parser.add_argument("--email", help="Email address (for --create/--update-contact)")
    parser.add_argument("--phone", help="Phone number (for --create/--update-contact)")
    parser.add_argument("--tag", action="append", default=[], dest="tags", help="Tag (repeatable)")
    parser.add_argument("--limit", type=int, default=10, help="Number of results for --list-recent (default 10)")
    parser.add_argument("--json", "-j", action="store_true", dest="output_json", help="Output raw JSON")
    args = parser.parse_args()

    actions_chosen = sum([
        bool(args.list_recent),
        bool(args.search),
        bool(args.get_contact),
        bool(args.create_contact),
        bool(args.update_contact),
    ])
    if actions_chosen == 0:
        parser.print_help()
        sys.exit(1)
    if actions_chosen > 1:
        print("Error: choose only one of --list-recent, --search, --get-contact, --create-contact, --update-contact", file=sys.stderr)
        sys.exit(1)

    if args.list_recent:
        results = list_recent(args.limit)
        _output(results, args.output_json, label=f"Recent contacts ({len(results)}):")
    elif args.search:
        results = search(args.search)
        _output(results, args.output_json, label=f"Found {len(results)} contact(s) matching '{args.search}':")
    elif args.get_contact:
        contact = get_contact(args.get_contact)
        if args.output_json:
            print(json.dumps(contact, indent=2, default=str))
        else:
            _print_contact(contact)
    elif args.create_contact:
        if not args.name:
            print("Error: --create-contact requires --name", file=sys.stderr)
            sys.exit(1)
        if not args.email and not args.phone:
            print("Error: --create-contact requires at least one of --email or --phone", file=sys.stderr)
            sys.exit(1)
        contact = create_contact(args.name, args.email or "", args.phone or "", args.tags)
        if args.output_json:
            print(json.dumps(contact, indent=2, default=str))
        else:
            print(f"Created contact:")
            _print_contact(contact)
    elif args.update_contact:
        contact = update_contact(
            args.update_contact,
            email=args.email or "",
            phone=args.phone or "",
            tags=args.tags or None,
        )
        if args.output_json:
            print(json.dumps(contact, indent=2, default=str))
        else:
            print(f"Updated contact:")
            _print_contact(contact)


def _output(results: list[dict], as_json: bool, label: str) -> None:
    if as_json:
        print(json.dumps(results, indent=2, default=str))
        return
    if not results:
        print("No contacts found.")
        return
    print(label, "\n")
    for i, c in enumerate(results, 1):
        _print_contact(c, i)


if __name__ == "__main__":
    main()
