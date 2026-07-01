#!/usr/bin/env python3
"""Mark a gateway lead terminal so the queue reflects the outcome.

Closes the loop opened by poll_leads.py: once a lead reaches a final state the
engine reports it back so the gateway stops considering it active and per-source
analytics are accurate.

  POST {NODESK_BASE_URL}/api/leads/mark
  header X-Hermes-Token: <client_id>
  body  {lead_id, status, client_id}

Valid terminal statuses: done | declined | opted_out | unresponsive
  done         -> appointment booked / handed off successfully
  declined     -> lead explicitly not interested
  opted_out    -> STOP/UNSUBSCRIBE (also stop all future texts to this number)
  unresponsive -> ghosted after the full follow-up ladder
"""
import argparse
import json
import os
import sys

import requests

BASE = os.environ.get("NODESK_BASE_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("HERMES_CLIENT_ID", "")
VALID = ("done", "declined", "opted_out", "unresponsive")


def main() -> int:
    ap = argparse.ArgumentParser(description="Mark a gateway lead terminal")
    ap.add_argument("--lead-id", required=True, help="the gateway lead_id from poll_leads.py")
    ap.add_argument("--status", required=True, choices=VALID)
    args = ap.parse_args()

    if not BASE or not CLIENT_ID:
        print(json.dumps({"error": "NODESK_BASE_URL or HERMES_CLIENT_ID not set in .env"}))
        return 1

    try:
        resp = requests.post(
            f"{BASE}/api/leads/mark",
            json={"lead_id": args.lead_id, "status": args.status, "client_id": CLIENT_ID},
            headers={"X-Hermes-Token": CLIENT_ID},
            timeout=30,
        )
        resp.raise_for_status()
        print(json.dumps(resp.json()))
        return 0
    except requests.RequestException as e:
        print(json.dumps({"error": str(e), "lead_id": args.lead_id, "status": args.status}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
