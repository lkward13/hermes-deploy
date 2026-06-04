#!/usr/bin/env python3
"""
Google Sheets CLI for Hermes agents.

Usage:
  python gsheets.py list                                                       # list sheets the agent created or owns
  python gsheets.py create --title "Q3 Leads"                                  # create a new spreadsheet, prints id + url
  python gsheets.py read --id <spreadsheet_id> [--range "Sheet1!A1:D10"]       # read a range
  python gsheets.py write --id <spreadsheet_id> --range "Sheet1!A1" --values '[["a","b"],["c","d"]]'   # overwrite a range
  python gsheets.py append --id <spreadsheet_id> --range "Sheet1!A1" --values '[["lead 1","555"]]'    # append rows
  python gsheets.py share --id <spreadsheet_id> --email user@example.com [--role writer]              # share a sheet

Scope: requires https://www.googleapis.com/auth/spreadsheets (read+write).

The agent only sees sheets it CREATED itself (drive.file scope on Drive side).
Customer's pre-existing spreadsheets are not visible via `list`; the customer
must either share each one with the agent's Google account OR the agent
creates new ones via `create`.
"""

import argparse
import json
import sys

import requests

from google_auth import get_valid_token

SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"


def headers():
    return {"Authorization": f"Bearer {get_valid_token()}"}


def cmd_list(args):
    # Drive API filter — only files of MIME type Sheets, sorted by recent.
    resp = requests.get(
        f"{DRIVE_BASE}/files",
        headers=headers(),
        params={
            "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            "fields": "files(id,name,createdTime,modifiedTime,webViewLink,owners(emailAddress))",
            "orderBy": "modifiedTime desc",
            "pageSize": args.max,
        },
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("files", [])
    out = [
        {
            "id": f["id"],
            "name": f.get("name", ""),
            "created": f.get("createdTime", ""),
            "modified": f.get("modifiedTime", ""),
            "url": f.get("webViewLink", ""),
            "owner": (f.get("owners") or [{}])[0].get("emailAddress", ""),
        }
        for f in items
    ]
    print(json.dumps(out, indent=2))


def cmd_create(args):
    body = {"properties": {"title": args.title}}
    resp = requests.post(SHEETS_BASE, headers={**headers(), "Content-Type": "application/json"}, json=body, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "id": data.get("spreadsheetId"),
        "url": data.get("spreadsheetUrl"),
        "title": (data.get("properties") or {}).get("title", args.title),
    }, indent=2))


def cmd_read(args):
    rng = args.range or "Sheet1"
    resp = requests.get(
        f"{SHEETS_BASE}/{args.id}/values/{rng}",
        headers=headers(),
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "range": data.get("range"),
        "values": data.get("values", []),
    }, indent=2))


def cmd_write(args):
    try:
        values = json.loads(args.values)
    except json.JSONDecodeError as exc:
        print(f"--values must be JSON (list of lists): {exc}", file=sys.stderr)
        sys.exit(2)
    body = {"values": values}
    resp = requests.put(
        f"{SHEETS_BASE}/{args.id}/values/{args.range}",
        headers={**headers(), "Content-Type": "application/json"},
        params={"valueInputOption": "USER_ENTERED"},
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "updatedRange": data.get("updatedRange"),
        "updatedRows": data.get("updatedRows"),
        "updatedColumns": data.get("updatedColumns"),
        "updatedCells": data.get("updatedCells"),
    }, indent=2))


def cmd_append(args):
    try:
        values = json.loads(args.values)
    except json.JSONDecodeError as exc:
        print(f"--values must be JSON (list of lists): {exc}", file=sys.stderr)
        sys.exit(2)
    body = {"values": values}
    resp = requests.post(
        f"{SHEETS_BASE}/{args.id}/values/{args.range}:append",
        headers={**headers(), "Content-Type": "application/json"},
        params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    u = data.get("updates", {})
    print(json.dumps({
        "updatedRange": u.get("updatedRange"),
        "updatedRows": u.get("updatedRows"),
        "updatedCells": u.get("updatedCells"),
    }, indent=2))


def cmd_share(args):
    body = {"type": "user", "role": args.role, "emailAddress": args.email}
    resp = requests.post(
        f"{DRIVE_BASE}/files/{args.id}/permissions",
        headers={**headers(), "Content-Type": "application/json"},
        params={"sendNotificationEmail": "true"},
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "id": data.get("id"),
        "type": data.get("type"),
        "role": data.get("role"),
        "emailAddress": data.get("emailAddress"),
    }, indent=2))


def main():
    p = argparse.ArgumentParser(description="Google Sheets CLI for Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="List spreadsheets the agent can access")
    pl.add_argument("--max", type=int, default=20)

    pc = sub.add_parser("create", help="Create a new spreadsheet")
    pc.add_argument("--title", required=True)

    pr = sub.add_parser("read", help="Read a range from a spreadsheet")
    pr.add_argument("--id", required=True, help="spreadsheet id")
    pr.add_argument("--range", help="A1 notation, e.g. Sheet1!A1:D10 (default: Sheet1)")

    pw = sub.add_parser("write", help="Overwrite a range with values")
    pw.add_argument("--id", required=True)
    pw.add_argument("--range", required=True)
    pw.add_argument("--values", required=True, help='JSON list of lists, e.g. [["a","b"],["c","d"]]')

    pa = sub.add_parser("append", help="Append rows after the last row in a range")
    pa.add_argument("--id", required=True)
    pa.add_argument("--range", required=True)
    pa.add_argument("--values", required=True)

    ps = sub.add_parser("share", help="Share a sheet with someone")
    ps.add_argument("--id", required=True)
    ps.add_argument("--email", required=True)
    ps.add_argument("--role", default="writer", choices=["reader", "commenter", "writer"])

    args = p.parse_args()
    fn = {
        "list": cmd_list,
        "create": cmd_create,
        "read": cmd_read,
        "write": cmd_write,
        "append": cmd_append,
        "share": cmd_share,
    }[args.cmd]
    try:
        fn(args)
    except requests.HTTPError as exc:
        print(f"HTTP {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
