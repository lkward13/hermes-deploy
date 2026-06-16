#!/usr/bin/env python3
"""GoHighLevel (HighLevel / LeadConnector v2) helper for the Hermes agent.

Covers the four things the agent does in GHL: reply to leads/conversations,
manage contacts, manage opportunities/pipelines, and book appointments.

Auth comes from NoDesk's credential sync (env in ``$HOME/.hermes/.env``):
    GHL_ACCESS_TOKEN   - OAuth bearer (auto-refreshed by NoDesk)
    GHL_LOCATION_ID    - the connected sub-account; every call scopes to it

All requests go to the v2 LeadConnector API with the required ``Version`` header.

NOTE: built from the LeadConnector v2 spec; some endpoint shapes (param casing,
response keys) should be verified against a live connected location — run the
commands once a real GHL account is connected and adjust if a call 4xxs.

Usage:
    # Contacts
    python3 ghl.py contacts-search --query "Jane Doe"
    python3 ghl.py contacts-search --phone "+14055551234"
    python3 ghl.py contact-create --first Jane --last Doe --phone "+14055551234" --email j@x.com
    python3 ghl.py contact-update --id <contactId> --tags "hot-lead,nurture"

    # Conversations / messaging
    python3 ghl.py conversations --contact-id <contactId>
    python3 ghl.py send-message --contact-id <contactId> --channel SMS --message "Hi, following up!"
    python3 ghl.py send-message --contact-id <contactId> --channel Email --subject "Quote" --message "..."

    # Opportunities / pipelines
    python3 ghl.py pipelines
    python3 ghl.py opportunities-search --query "Jane"
    python3 ghl.py opportunity-create --name "Jane Doe - Roof" --pipeline-id <pid> --stage-id <sid> --contact-id <cid> --value 5000
    python3 ghl.py opportunity-update --id <oppId> --stage-id <sid> --status open

    # Calendars / appointments
    python3 ghl.py calendars
    python3 ghl.py free-slots --calendar-id <calId> --start 2026-06-20 --end 2026-06-21
    python3 ghl.py book-appointment --calendar-id <calId> --contact-id <cid> --start "2026-06-20T15:00:00-05:00" --title "Consult"

Add --json to any command for raw JSON output.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

API = "https://services.leadconnectorhq.com"
VERSION = "2021-07-28"
TIMEOUT = 20


def _load_env() -> None:
    """Best-effort load of ~/.hermes/.env so the skill works outside the gateway."""
    env_path = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _cfg():
    _load_env()
    token = os.environ.get("GHL_ACCESS_TOKEN", "")
    loc = os.environ.get("GHL_LOCATION_ID", "")
    if not token or not loc:
        _die("GHL not connected: GHL_ACCESS_TOKEN / GHL_LOCATION_ID missing from "
             "the agent .env. The customer must connect GoHighLevel on the NoDesk "
             "connect portal first.")
    return token, loc


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Version": VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _req(method: str, path: str, *, params=None, body=None):
    token, _ = _cfg()
    url = f"{API}{path}"
    try:
        r = requests.request(method, url, headers=_headers(token),
                             params=params, json=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        _die(f"request failed: {e}")
    if r.status_code == 401:
        _die("401 Unauthorized — the GHL access token is invalid/expired. NoDesk "
             "refreshes it on credential sync; if this persists the customer must "
             "reconnect GoHighLevel.")
    if not r.ok:
        _die(f"HTTP {r.status_code} on {method} {path}: {r.text[:400]}")
    return r.json() if r.text else {}


def _die(msg: str):
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(1)


def _out(data, as_json: bool, summarize=None):
    if as_json or summarize is None:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(summarize(data))


# ---- Contacts ----

def contacts_search(args):
    _, loc = _cfg()
    params = {"locationId": loc}
    if args.query:
        params["query"] = args.query
    if args.phone:
        params["query"] = args.phone
    if args.email:
        params["query"] = args.email
    data = _req("GET", "/contacts/", params=params)
    def s(d):
        cs = d.get("contacts", d.get("data", []))
        if not cs:
            return "No contacts found."
        return "\n".join(
            f"- {c.get('contactName') or (c.get('firstName','')+' '+c.get('lastName','')).strip()} "
            f"| {c.get('phone','')} {c.get('email','')} | id={c.get('id')}"
            for c in cs[:25]
        )
    _out(data, args.json, s)


def contact_create(args):
    _, loc = _cfg()
    body = {"locationId": loc}
    if args.first: body["firstName"] = args.first
    if args.last: body["lastName"] = args.last
    if args.phone: body["phone"] = args.phone
    if args.email: body["email"] = args.email
    if args.tags: body["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    data = _req("POST", "/contacts/", body=body)
    _out(data, args.json, lambda d: f"Created contact id={d.get('contact',{}).get('id') or d.get('id')}")


def contact_update(args):
    body = {}
    if args.first: body["firstName"] = args.first
    if args.last: body["lastName"] = args.last
    if args.phone: body["phone"] = args.phone
    if args.email: body["email"] = args.email
    if args.tags: body["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    data = _req("PUT", f"/contacts/{args.id}", body=body)
    _out(data, args.json, lambda d: f"Updated contact {args.id}")


# ---- Conversations / messaging ----

def conversations(args):
    _, loc = _cfg()
    params = {"locationId": loc}
    if args.contact_id:
        params["contactId"] = args.contact_id
    data = _req("GET", "/conversations/search", params=params)
    def s(d):
        cs = d.get("conversations", d.get("data", []))
        if not cs:
            return "No conversations."
        return "\n".join(
            f"- {c.get('contactName','?')} | last: {(c.get('lastMessageBody') or '')[:60]!r} | id={c.get('id')}"
            for c in cs[:25]
        )
    _out(data, args.json, s)


def send_message(args):
    body = {
        "type": args.channel,            # "SMS" or "Email"
        "contactId": args.contact_id,
        "message": args.message,
    }
    if args.channel.lower() == "email" and args.subject:
        body["subject"] = args.subject
    data = _req("POST", "/conversations/messages", body=body)
    _out(data, args.json, lambda d: f"Sent {args.channel} to contact {args.contact_id}")


# ---- Opportunities / pipelines ----

def pipelines(args):
    _, loc = _cfg()
    data = _req("GET", "/opportunities/pipelines", params={"locationId": loc})
    def s(d):
        ps = d.get("pipelines", [])
        out = []
        for p in ps:
            out.append(f"Pipeline: {p.get('name')} (id={p.get('id')})")
            for st in p.get("stages", []):
                out.append(f"    stage: {st.get('name')} (id={st.get('id')})")
        return "\n".join(out) or "No pipelines."
    _out(data, args.json, s)


def opportunities_search(args):
    _, loc = _cfg()
    params = {"location_id": loc}
    if args.query:
        params["q"] = args.query
    data = _req("GET", "/opportunities/search", params=params)
    def s(d):
        os_ = d.get("opportunities", d.get("data", []))
        if not os_:
            return "No opportunities."
        return "\n".join(
            f"- {o.get('name')} | {o.get('status')} | ${o.get('monetaryValue','')} | id={o.get('id')}"
            for o in os_[:25]
        )
    _out(data, args.json, s)


def opportunity_create(args):
    _, loc = _cfg()
    body = {
        "locationId": loc,
        "name": args.name,
        "pipelineId": args.pipeline_id,
        "pipelineStageId": args.stage_id,
        "status": args.status or "open",
    }
    if args.contact_id: body["contactId"] = args.contact_id
    if args.value is not None: body["monetaryValue"] = args.value
    data = _req("POST", "/opportunities/", body=body)
    _out(data, args.json, lambda d: f"Created opportunity id={d.get('opportunity',{}).get('id') or d.get('id')}")


def opportunity_update(args):
    body = {}
    if args.stage_id: body["pipelineStageId"] = args.stage_id
    if args.status: body["status"] = args.status
    if args.value is not None: body["monetaryValue"] = args.value
    data = _req("PUT", f"/opportunities/{args.id}", body=body)
    _out(data, args.json, lambda d: f"Updated opportunity {args.id}")


# ---- Calendars / appointments ----

def calendars(args):
    _, loc = _cfg()
    data = _req("GET", "/calendars/", params={"locationId": loc})
    def s(d):
        cs = d.get("calendars", [])
        return "\n".join(f"- {c.get('name')} (id={c.get('id')})" for c in cs) or "No calendars."
    _out(data, args.json, s)


def free_slots(args):
    params = {"startDate": args.start, "endDate": args.end}
    data = _req("GET", f"/calendars/{args.calendar_id}/free-slots", params=params)
    _out(data, args.json, None)


def book_appointment(args):
    _, loc = _cfg()
    body = {
        "calendarId": args.calendar_id,
        "locationId": loc,
        "contactId": args.contact_id,
        "startTime": args.start,
        "title": args.title or "Appointment",
    }
    if args.end: body["endTime"] = args.end
    data = _req("POST", "/calendars/events/appointments", body=body)
    _out(data, args.json, lambda d: f"Booked appointment id={d.get('id') or d.get('event',{}).get('id')}")


def main():
    p = argparse.ArgumentParser(description="GoHighLevel agent helper")
    p.add_argument("--json", action="store_true", help="raw JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("contacts-search"); c.add_argument("--query"); c.add_argument("--phone"); c.add_argument("--email"); c.set_defaults(fn=contacts_search)
    c = sub.add_parser("contact-create"); c.add_argument("--first"); c.add_argument("--last"); c.add_argument("--phone"); c.add_argument("--email"); c.add_argument("--tags"); c.set_defaults(fn=contact_create)
    c = sub.add_parser("contact-update"); c.add_argument("--id", required=True); c.add_argument("--first"); c.add_argument("--last"); c.add_argument("--phone"); c.add_argument("--email"); c.add_argument("--tags"); c.set_defaults(fn=contact_update)

    c = sub.add_parser("conversations"); c.add_argument("--contact-id", dest="contact_id"); c.set_defaults(fn=conversations)
    c = sub.add_parser("send-message"); c.add_argument("--contact-id", dest="contact_id", required=True); c.add_argument("--channel", default="SMS"); c.add_argument("--message", required=True); c.add_argument("--subject"); c.set_defaults(fn=send_message)

    c = sub.add_parser("pipelines"); c.set_defaults(fn=pipelines)
    c = sub.add_parser("opportunities-search"); c.add_argument("--query"); c.set_defaults(fn=opportunities_search)
    c = sub.add_parser("opportunity-create"); c.add_argument("--name", required=True); c.add_argument("--pipeline-id", dest="pipeline_id", required=True); c.add_argument("--stage-id", dest="stage_id", required=True); c.add_argument("--contact-id", dest="contact_id"); c.add_argument("--value", type=float); c.add_argument("--status"); c.set_defaults(fn=opportunity_create)
    c = sub.add_parser("opportunity-update"); c.add_argument("--id", required=True); c.add_argument("--stage-id", dest="stage_id"); c.add_argument("--status"); c.add_argument("--value", type=float); c.set_defaults(fn=opportunity_update)

    c = sub.add_parser("calendars"); c.set_defaults(fn=calendars)
    c = sub.add_parser("free-slots"); c.add_argument("--calendar-id", dest="calendar_id", required=True); c.add_argument("--start", required=True); c.add_argument("--end", required=True); c.set_defaults(fn=free_slots)
    c = sub.add_parser("book-appointment"); c.add_argument("--calendar-id", dest="calendar_id", required=True); c.add_argument("--contact-id", dest="contact_id", required=True); c.add_argument("--start", required=True); c.add_argument("--end"); c.add_argument("--title"); c.set_defaults(fn=book_appointment)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
