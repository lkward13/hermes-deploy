#!/usr/bin/env python3
"""Check for inbound SMS via ClickSend REST API."""
import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

CLICKSEND_USERNAME = os.environ.get("CLICKSEND_USERNAME", "")
CLICKSEND_API_KEY = os.environ.get("CLICKSEND_API_KEY", "")
INBOUND_URL = "https://rest.clicksend.com/v3/sms/inbound"


def get_auth_header() -> str:
    return base64.b64encode(f"{CLICKSEND_USERNAME}:{CLICKSEND_API_KEY}".encode()).decode()


def fetch_inbound(page: int = 1, limit: int = 100) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {get_auth_header()}",
    }
    params = {"page": page, "limit": limit}
    resp = requests.get(INBOUND_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Check inbound SMS via ClickSend")
    parser.add_argument("--from", dest="from_number", help="Filter by sender phone number")
    parser.add_argument("--since", type=int, default=60, help="Only show messages from last N minutes (default: 60)")
    parser.add_argument("--json", dest="output_json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.since)

    result = fetch_inbound()
    messages = result.get("data", {}).get("data", [])

    filtered = []
    for msg in messages:
        ts = msg.get("timestamp")
        if ts:
            msg_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            if msg_time < cutoff:
                continue

        sender = msg.get("from", "")
        if args.from_number:
            normalized_filter = args.from_number.replace("+", "").replace("-", "").replace(" ", "")
            normalized_sender = sender.replace("+", "").replace("-", "").replace(" ", "")
            if not normalized_sender.endswith(normalized_filter.lstrip("1")) and normalized_filter not in normalized_sender:
                continue

        filtered.append(msg)

    if args.output_json:
        print(json.dumps(filtered, indent=2))
    elif not filtered:
        print("No inbound messages found.")
    else:
        for msg in filtered:
            ts = msg.get("timestamp", "")
            if ts:
                ts = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"From: {msg.get('from', '?')} | To: {msg.get('to', '?')} | Time: {ts}")
            print(f"Body: {msg.get('body', '')}")
            print("---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
