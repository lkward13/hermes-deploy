#!/usr/bin/env python3
"""Poll Facebook Graph API for new leads."""
import json
import os
import sys

import requests

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
LEADS_FILE = os.path.join(SKILL_DIR, "leads.json")

PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
FORM_ID = os.environ.get("FB_FORM_ID", "")
GRAPH_API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FORM_ID}/leads"


def load_known_lead_ids() -> set:
    if not os.path.exists(LEADS_FILE):
        return set()
    with open(LEADS_FILE, "r") as f:
        data = json.load(f)
    return {lead.get("fb_lead_id") for lead in data.get("leads", {}).values() if lead.get("fb_lead_id")}


def fetch_leads(limit: int = 25) -> list:
    params = {
        "access_token": PAGE_ACCESS_TOKEN,
        "limit": limit,
        "fields": "id,created_time,field_data",
    }
    resp = requests.get(GRAPH_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])


def parse_lead(raw: dict) -> dict:
    fields = {}
    for fd in raw.get("field_data", []):
        name = fd.get("name", "").lower().replace(" ", "_")
        values = fd.get("values", [])
        fields[name] = values[0] if len(values) == 1 else values

    name_parts = []
    if fields.get("first_name"):
        name_parts.append(fields["first_name"])
    if fields.get("last_name"):
        name_parts.append(fields["last_name"])
    full_name = " ".join(name_parts) if name_parts else fields.get("full_name", "Unknown")

    phone = fields.get("phone_number", fields.get("phone", ""))
    email = fields.get("email", "")

    return {
        "fb_lead_id": raw.get("id", ""),
        "name": full_name,
        "phone": phone,
        "email": email,
        "created_time": raw.get("created_time", ""),
        "form_data": fields,
    }


def main():
    known_ids = load_known_lead_ids()
    try:
        raw_leads = fetch_leads()
    except requests.RequestException as e:
        print(json.dumps({"error": str(e), "new_leads": []}))
        return 1

    new_leads = []
    for raw in raw_leads:
        lead_id = raw.get("id", "")
        if lead_id and lead_id not in known_ids:
            parsed = parse_lead(raw)
            if parsed["phone"]:
                new_leads.append(parsed)

    output = {"new_leads": new_leads, "total_fetched": len(raw_leads), "known_count": len(known_ids)}
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
