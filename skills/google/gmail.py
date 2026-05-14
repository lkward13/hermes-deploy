#!/usr/bin/env python3
"""
Gmail CLI for Hermes agents.

Usage:
  python gmail.py send --to user@example.com --subject "Hello" --body "Message body"
  python gmail.py list [--max 10] [--query "is:unread"]
  python gmail.py read --id <message_id>
"""
import argparse
import base64
import json
import sys

import requests

from google_auth import get_valid_token


def _build_raw(to, subject, body, cc=None):
    """Build a base64url-encoded RFC 2822 message without importing stdlib email."""
    headers = [
        f"To: {to}",
        f"Subject: {subject}",
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=utf-8",
    ]
    if cc:
        headers.append(f"Cc: {cc}")
    raw = "\r\n".join(headers) + "\r\n\r\n" + body
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode()

BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def headers():
    return {"Authorization": f"Bearer {get_valid_token()}"}


def cmd_send(args):
    raw = _build_raw(args.to, args.subject, args.body, cc=args.cc or None)
    resp = requests.post(f"{BASE}/messages/send", headers=headers(), json={"raw": raw}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps({"status": "sent", "id": data.get("id"), "threadId": data.get("threadId")}))


def cmd_list(args):
    params = {"maxResults": args.max}
    if args.query:
        params["q"] = args.query
    resp = requests.get(f"{BASE}/messages", headers=headers(), params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    messages = data.get("messages", [])

    results = []
    for m in messages[:args.max]:
        detail = requests.get(
            f"{BASE}/messages/{m['id']}",
            headers=headers(),
            params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            timeout=15,
        ).json()
        headers_list = detail.get("payload", {}).get("headers", [])
        h = {h["name"]: h["value"] for h in headers_list}
        results.append({
            "id": m["id"],
            "from": h.get("From", ""),
            "subject": h.get("Subject", ""),
            "date": h.get("Date", ""),
            "snippet": detail.get("snippet", ""),
        })

    print(json.dumps(results, indent=2))


def cmd_read(args):
    resp = requests.get(f"{BASE}/messages/{args.id}", headers=headers(), params={"format": "full"}, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    payload = data.get("payload", {})
    headers_list = payload.get("headers", [])
    h = {hdr["name"]: hdr["value"] for hdr in headers_list}

    body = ""
    parts = payload.get("parts", [payload])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            body_data = part.get("body", {}).get("data", "")
            if body_data:
                body = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
                break

    print(json.dumps({
        "id": data["id"],
        "from": h.get("From", ""),
        "to": h.get("To", ""),
        "subject": h.get("Subject", ""),
        "date": h.get("Date", ""),
        "body": body[:4000],
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Gmail CLI for Hermes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("send", help="Send an email")
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--subject", required=True)
    p_send.add_argument("--body", required=True)
    p_send.add_argument("--cc", default="")

    p_list = sub.add_parser("list", help="List recent emails")
    p_list.add_argument("--max", type=int, default=10)
    p_list.add_argument("--query", default="")

    p_read = sub.add_parser("read", help="Read a specific email")
    p_read.add_argument("--id", required=True)

    args = parser.parse_args()
    try:
        if args.command == "send":
            cmd_send(args)
        elif args.command == "list":
            cmd_list(args)
        elif args.command == "read":
            cmd_read(args)
    except requests.HTTPError as e:
        print(json.dumps({"error": str(e), "response": e.response.text if e.response else None}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
