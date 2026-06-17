#!/usr/bin/env python3
"""Poll the NoDesk gateway lead queue for new (pending) leads.

Source-agnostic. Every connected source — Facebook, Jobber, GoHighLevel,
BoldTrail, Podio, website forms, CallRail, manual entry — funnels into the
gateway's canonical Lead queue. This script polls that one queue for the
tenant, so the engine no longer cares where a lead came from.

Endpoint (shipped, NoDesk PR #74):
  GET {NODESK_BASE_URL}/api/leads/pending?client_id=<id>&claim=true
  header X-Hermes-Token: <client_id>   (same per-tenant secret as /api/push)
  -> {"leads": [ {lead_id, source, external_id, name, phone, email,
                  address, service_type, message, status, received_at}, ... ],
      "count": N}

`claim=true` (default) flips each returned row pending -> claimed server-side,
so a lead is handed to the engine exactly once. Use --no-claim to peek during
testing without consuming the queue.
"""
import argparse
import json
import os
import sys

import requests

BASE = os.environ.get("NODESK_BASE_URL", "").rstrip("/")
CLIENT_ID = os.environ.get("HERMES_CLIENT_ID", "")


def fetch_pending(claim: bool = True, timeout: int = 30) -> dict:
    resp = requests.get(
        f"{BASE}/api/leads/pending",
        params={"client_id": CLIENT_ID, "claim": "true" if claim else "false"},
        headers={"X-Hermes-Token": CLIENT_ID},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    ap = argparse.ArgumentParser(description="Poll the NoDesk gateway lead queue")
    ap.add_argument(
        "--no-claim",
        action="store_true",
        help="peek without claiming (testing only; leads stay pending)",
    )
    args = ap.parse_args()

    if not BASE or not CLIENT_ID:
        print(json.dumps({
            "error": "NODESK_BASE_URL or HERMES_CLIENT_ID not set in .env",
            "new_leads": [], "count": 0,
        }))
        return 1

    try:
        data = fetch_pending(claim=not args.no_claim)
    except requests.RequestException as e:
        print(json.dumps({"error": str(e), "new_leads": [], "count": 0}))
        return 1

    # Only surface leads we can actually text. A lead with no phone is a
    # data problem upstream, not something the SMS engine can act on.
    new_leads = [lead for lead in data.get("leads", []) if lead.get("phone")]
    print(json.dumps({
        "new_leads": new_leads,
        "count": len(new_leads),
        "claimed": not args.no_claim,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
