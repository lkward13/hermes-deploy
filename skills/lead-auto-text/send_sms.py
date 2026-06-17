#!/usr/bin/env python3
"""Send SMS via ClickSend REST API."""
import argparse
import base64
import json
import os
import sys

import requests

CLICKSEND_USERNAME = os.environ.get("CLICKSEND_USERNAME", "")
CLICKSEND_API_KEY = os.environ.get("CLICKSEND_API_KEY", "")
CLICKSEND_FROM = os.environ.get("CLICKSEND_FROM", "")
API_URL = "https://rest.clicksend.com/v3/sms/send"


def send_sms(to: str, body: str, from_number: str = CLICKSEND_FROM) -> dict:
    auth_string = base64.b64encode(f"{CLICKSEND_USERNAME}:{CLICKSEND_API_KEY}".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_string}",
    }
    payload = {
        "messages": [
            {
                "from": from_number,
                "to": to,
                "body": body,
                "source": "hermes-lead-auto-text",
            }
        ]
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Send SMS via ClickSend")
    parser.add_argument("--to", required=True, help="Destination phone number (E.164 format)")
    parser.add_argument("--body", required=True, help="Message body")
    parser.add_argument("--from", dest="from_number", default=CLICKSEND_FROM, help="Sender number")
    parser.add_argument(
        "--respect-quiet-hours",
        action="store_true",
        help="LEAD texts only: refuse to send outside the tenant's local texting "
             "window (see quiet_hours.py). Do NOT pass this for owner/admin "
             "notifications — those are exempt and must always go through.",
    )
    args = parser.parse_args()

    if args.respect_quiet_hours:
        # Hard guard: a lead-facing text during quiet hours never leaves the box,
        # even if the LLM forgot to check. Owner notifications skip this flag.
        from quiet_hours import text_ok_now
        ok, info = text_ok_now()
        if not ok:
            print(json.dumps({"sent": False, "reason": "quiet_hours", **info}))
            return 2

    body = args.body.replace("\\n", "\n")
    result = send_sms(args.to, body, args.from_number)

    messages = result.get("data", {}).get("messages", [])
    for msg in messages:
        status = msg.get("status", "unknown")
        msg_id = msg.get("message_id", "n/a")
        print(f"Status: {status} | Message ID: {msg_id} | To: {msg.get('to', args.to)}")

    if not messages:
        print(json.dumps(result, indent=2))

    if messages and all(m.get("status") == "SUCCESS" for m in messages):
        # NoDesk activity chip: surfaces a subtle "💬 Texted a lead" in the app.
        # The gateway parses this marker from tool output and strips it.
        print("[[NODESK_ACTIVITY|💬|Texted a lead|action]]")
    return 0 if all(m.get("status") == "SUCCESS" for m in messages) else 1


if __name__ == "__main__":
    sys.exit(main())
