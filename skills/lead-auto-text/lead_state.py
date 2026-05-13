#!/usr/bin/env python3
"""Manage lead conversation state in a JSON file."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

LEADS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.json")

VALID_STATUSES = ["new", "contacted", "in_conversation", "pending_approval", "confirmed", "declined", "unresponsive"]


def load_leads() -> dict:
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r") as f:
            return json.load(f)
    return {"leads": {}, "updated_at": None}


def save_leads(data: dict):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(LEADS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def cmd_add(args):
    data = load_leads()
    phone = normalize_phone(args.phone)
    if phone in data["leads"]:
        print(f"Lead {phone} already exists (status: {data['leads'][phone]['status']})")
        return 1

    now = datetime.now(timezone.utc).isoformat()
    data["leads"][phone] = {
        "name": args.name,
        "phone": phone,
        "email": args.email or "",
        "source": args.source or "facebook",
        "fb_lead_id": args.fb_lead_id or "",
        "status": "new",
        "created_at": now,
        "updated_at": now,
        "proposed_time": None,
        "owner_approvals": {},
        "form_data": {},
        "conversation": [],
    }
    save_leads(data)
    print(f"Added lead: {args.name} ({phone}) — status: new")
    return 0


def cmd_update(args):
    data = load_leads()
    phone = normalize_phone(args.phone)
    if phone not in data["leads"]:
        print(f"Lead {phone} not found.")
        return 1

    lead = data["leads"][phone]
    if args.status:
        if args.status not in VALID_STATUSES:
            print(f"Invalid status. Valid: {', '.join(VALID_STATUSES)}")
            return 1
        lead["status"] = args.status
    if args.proposed_time:
        lead["proposed_time"] = args.proposed_time
    if args.approval_from and args.approval_value:
        lead.setdefault("owner_approvals", {})[args.approval_from] = args.approval_value
    if args.form_data:
        lead.setdefault("form_data", {}).update(json.loads(args.form_data))

    lead["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_leads(data)
    print(f"Updated lead {phone}: status={lead['status']}")
    return 0


def cmd_log_message(args):
    data = load_leads()
    phone = normalize_phone(args.phone)
    if phone not in data["leads"]:
        print(f"Lead {phone} not found.")
        return 1

    lead = data["leads"][phone]
    lead["conversation"].append({
        "direction": args.direction,
        "body": args.body,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    lead["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_leads(data)
    print(f"Logged {args.direction} message for {phone}")
    return 0


def cmd_get(args):
    data = load_leads()
    phone = normalize_phone(args.phone)
    lead = data["leads"].get(phone)
    if not lead:
        print(f"Lead {phone} not found.")
        return 1
    print(json.dumps(lead, indent=2))
    return 0


def cmd_list(args):
    data = load_leads()
    leads = data["leads"]
    if args.status:
        leads = {k: v for k, v in leads.items() if v["status"] == args.status}
    if not leads:
        print("No leads found.")
        return 0
    for phone, lead in leads.items():
        convos = len(lead.get("conversation", []))
        print(f"{lead['name']:20s} | {phone:15s} | {lead['status']:20s} | {convos} msgs | {lead.get('source', '?')}")
    return 0


def cmd_active_phones(args):
    """Output phone numbers of leads in active conversation states (for cron polling)."""
    data = load_leads()
    active_statuses = {"contacted", "in_conversation", "pending_approval"}
    phones = [phone for phone, lead in data["leads"].items() if lead["status"] in active_statuses]
    for p in phones:
        print(p)
    return 0



def cmd_lock(args):
    """Set a processing lock on a lead to prevent concurrent handling."""
    data = load_leads()
    phone = normalize_phone(args.phone)
    lead = data["leads"].get(phone)
    if not lead:
        print("NOT_FOUND")
        return 0
    existing_lock = lead.get("processing_lock")
    if existing_lock:
        lock_time = datetime.fromisoformat(existing_lock)
        if (datetime.now(timezone.utc) - lock_time).total_seconds() < 120:
            print("ALREADY_LOCKED")
            return 0
    lead["processing_lock"] = datetime.now(timezone.utc).isoformat()
    save_leads(data)
    print("LOCKED")
    return 0


def cmd_unlock(args):
    """Remove the processing lock from a lead."""
    data = load_leads()
    phone = normalize_phone(args.phone)
    lead = data["leads"].get(phone)
    if lead:
        lead["processing_lock"] = None
        save_leads(data)
    print("UNLOCKED")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Manage lead conversation state")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="Add a new lead")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--phone", required=True)
    p_add.add_argument("--email", default="")
    p_add.add_argument("--source", default="facebook")
    p_add.add_argument("--fb-lead-id", default="")

    p_update = sub.add_parser("update", help="Update lead fields")
    p_update.add_argument("--phone", required=True)
    p_update.add_argument("--status")
    p_update.add_argument("--proposed-time")
    p_update.add_argument("--approval-from")
    p_update.add_argument("--approval-value")
    p_update.add_argument("--form-data", help="JSON string of form data to merge")

    p_log = sub.add_parser("log-message", help="Log a conversation message")
    p_log.add_argument("--phone", required=True)
    p_log.add_argument("--direction", required=True, choices=["inbound", "outbound"])
    p_log.add_argument("--body", required=True)

    p_get = sub.add_parser("get", help="Get a single lead")
    p_get.add_argument("--phone", required=True)

    p_list = sub.add_parser("list", help="List leads")
    p_list.add_argument("--status", help="Filter by status")

    sub.add_parser("active-phones", help="List phone numbers in active states")

    p_lock = sub.add_parser("lock", help="Set processing lock on a lead")
    p_lock.add_argument("--phone", required=True)

    p_unlock = sub.add_parser("unlock", help="Remove processing lock from a lead")
    p_unlock.add_argument("--phone", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    cmds = {
        "add": cmd_add,
        "update": cmd_update,
        "log-message": cmd_log_message,
        "get": cmd_get,
        "list": cmd_list,
        "active-phones": cmd_active_phones,
        "lock": cmd_lock,
        "unlock": cmd_unlock,
    }
    return cmds[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
