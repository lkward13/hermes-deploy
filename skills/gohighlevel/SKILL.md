---
name: gohighlevel
description: Read & act in the customer's GoHighLevel CRM — reply to lead conversations (SMS/email), manage contacts, move opportunities through pipelines, and book appointments. OAuth-authenticated; no API key.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [GoHighLevel, HighLevel, CRM, leads, conversations, appointments]
---

# GoHighLevel

Work the customer's GoHighLevel (HighLevel / LeadConnector) sub-account: respond
to inbound leads, manage contacts, move opportunities through pipeline stages,
and book appointments. Authenticates via OAuth tokens NoDesk pushes to the
agent's `.env` — there is **no** API key or username/password flow.

## Authentication

Reads from `$HOME/.hermes/.env` (set by NoDesk after the customer connects
GoHighLevel on the connect portal):

- `GHL_ACCESS_TOKEN` — OAuth bearer; NoDesk auto-refreshes it via `GHL_REFRESH_TOKEN`.
- `GHL_LOCATION_ID` — the connected sub-account; every call is scoped to it automatically.

If a command returns **`GHL not connected`**, the customer hasn't connected
GoHighLevel yet — tell them to connect it on their NoDesk connect page. A `401`
means the token is mid-rotation or revoked; if it persists, they must reconnect.

## Commands

All commands run from the agent's venv. Add `--json` for raw output.

```bash
H=~/.hermes/skills/gohighlevel/ghl.py

# --- Contacts ---
python3 $H contacts-search --query "Jane Doe"
python3 $H contacts-search --phone "+14055551234"
python3 $H contact-create --first Jane --last Doe --phone "+14055551234" --email j@x.com --tags "website-lead"
python3 $H contact-update --id <contactId> --tags "hot-lead"

# --- Conversations / messaging (reply to leads) ---
python3 $H conversations --contact-id <contactId>
python3 $H send-message --contact-id <contactId> --channel SMS --message "Hi Jane! Following up on your request."
python3 $H send-message --contact-id <contactId> --channel Email --subject "Your quote" --message "Hi Jane, ..."

# --- Opportunities / pipelines ---
python3 $H pipelines                       # list pipelines + their stage IDs first
python3 $H opportunities-search --query "Jane"
python3 $H opportunity-create --name "Jane Doe - Roof" --pipeline-id <pid> --stage-id <sid> --contact-id <cid> --value 5000
python3 $H opportunity-update --id <oppId> --stage-id <sid> --status won

# --- Calendars / appointments ---
python3 $H calendars                       # list calendars + their IDs first
python3 $H free-slots --calendar-id <calId> --start 2026-06-20 --end 2026-06-21
python3 $H book-appointment --calendar-id <calId> --contact-id <cid> --start "2026-06-20T15:00:00-05:00" --title "Consultation"
```

## Tips for the agent

- **Find the contact first.** Most actions need a `contactId` — run `contacts-search`
  (by name or phone) before messaging, creating opportunities, or booking.
- **List pipelines/calendars before writing.** `opportunity-create` needs a
  `pipeline-id` + `stage-id`; `book-appointment` needs a `calendar-id`. Run
  `pipelines` / `calendars` to get the IDs, then act.
- **Replying to a lead** is usually `contacts-search` → `send-message --channel SMS`.
- Times for appointments are ISO‑8601 with the customer's timezone offset.

## Status

v1, built from the LeadConnector v2 API spec. The endpoint shapes should be
confirmed against a live connected location on first real use — if a specific
command returns a 4xx, the path/param/body for that one endpoint may need a
tweak (the auth + structure are correct).
