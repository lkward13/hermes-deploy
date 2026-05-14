#!/usr/bin/env python3
"""
Google Calendar CLI for Hermes agents.

Usage:
  python calendar.py list [--days 7] [--max 20]
  python calendar.py create --title "Meeting" --start "2026-05-15T10:00:00" --end "2026-05-15T11:00:00" [--description "..."] [--attendees "a@b.com,c@d.com"]
  python calendar.py delete --id <event_id>
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import requests

from google_auth import get_valid_token

BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"


def headers():
    return {"Authorization": f"Bearer {get_valid_token()}"}


def cmd_list(args):
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=args.days)).isoformat()

    resp = requests.get(
        f"{BASE}/events",
        headers=headers(),
        params={
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": args.max,
            "singleEvents": True,
            "orderBy": "startTime",
        },
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])

    results = []
    for e in items:
        start = e.get("start", {})
        end = e.get("end", {})
        results.append({
            "id": e.get("id"),
            "title": e.get("summary", "(no title)"),
            "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"),
            "location": e.get("location", ""),
            "description": e.get("description", "")[:300],
            "attendees": [a.get("email") for a in e.get("attendees", [])],
            "link": e.get("htmlLink", ""),
        })

    print(json.dumps(results, indent=2))


def cmd_create(args):
    body = {
        "summary": args.title,
        "start": {"dateTime": args.start, "timeZone": "America/Chicago"},
        "end": {"dateTime": args.end, "timeZone": "America/Chicago"},
    }
    if args.description:
        body["description"] = args.description
    if args.attendees:
        body["attendees"] = [{"email": e.strip()} for e in args.attendees.split(",") if e.strip()]

    resp = requests.post(f"{BASE}/events", headers=headers(), json=body, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({
        "status": "created",
        "id": data.get("id"),
        "title": data.get("summary"),
        "start": data.get("start", {}).get("dateTime"),
        "link": data.get("htmlLink"),
    }))


def cmd_delete(args):
    resp = requests.delete(f"{BASE}/events/{args.id}", headers=headers(), timeout=20)
    resp.raise_for_status()
    print(json.dumps({"status": "deleted", "id": args.id}))


def main():
    parser = argparse.ArgumentParser(description="Google Calendar CLI for Hermes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List upcoming events")
    p_list.add_argument("--days", type=int, default=7)
    p_list.add_argument("--max", type=int, default=20)

    p_create = sub.add_parser("create", help="Create an event")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--start", required=True, help="ISO datetime e.g. 2026-05-15T10:00:00")
    p_create.add_argument("--end", required=True, help="ISO datetime e.g. 2026-05-15T11:00:00")
    p_create.add_argument("--description", default="")
    p_create.add_argument("--attendees", default="", help="Comma-separated emails")

    p_delete = sub.add_parser("delete", help="Delete an event")
    p_delete.add_argument("--id", required=True)

    args = parser.parse_args()
    try:
        if args.command == "list":
            cmd_list(args)
        elif args.command == "create":
            cmd_create(args)
        elif args.command == "delete":
            cmd_delete(args)
    except requests.HTTPError as e:
        print(json.dumps({"error": str(e), "response": e.response.text if e.response else None}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
