---
name: podio
description: Full Podio CRM tool. Read any app's items (and a single item in full), discover apps, and write (create/update items, comments, tasks). OAuth-authenticated; no username/password needed.
version: 2.0.0
author: NoDesk
metadata:
  hermes:
    tags: [Podio, CRM, leads, items, tasks]
---

# Podio

Read and write the customer's Podio account. Podio is a flexible CRM/workspace: an organization holds spaces (workspaces), each space holds apps, each app holds items, and items have fields, comments, tasks, and files. This skill can read any app (not just the leads/jobs app), read a single item in full, discover app IDs, and write items, comments, and tasks.

Two scripts:

- `podio_lookup.py` reads (search, list, get one item, list apps, and the legacy status update).
- `podio_write.py` writes (create/update items, add comments, create/complete tasks).

Both share one auth layer: `podio_write.py` imports the OAuth and auto-refresh helpers directly from `podio_lookup.py`, so there is a single place that knows about tokens.

## Authentication

This skill reads credentials from `$HOME/.hermes/.env`:

- `PODIO_CLIENT_ID`
- `PODIO_CLIENT_SECRET`
- `PODIO_ACCESS_TOKEN` (set by NoDesk after the customer completes Podio OAuth on the connect portal; auto-refreshes via `PODIO_REFRESH_TOKEN`)
- `PODIO_REFRESH_TOKEN`
- `PODIO_APP_ID` (the numeric app ID for the default leads/jobs app, set per-customer)

Podio uses the literal authorization scheme `OAuth2 <token>` (not `Bearer`). The scripts handle this for you.

**Do NOT** check for `PODIO_USERNAME` or `PODIO_PASSWORD`. Those do not exist in this environment. If a call returns a 401, the access token is mid-rotation: the scripts automatically refresh via the refresh token and retry once. No manual intervention needed. If the token is genuinely missing, the writer exits with code 2.

## Read commands (`podio_lookup.py`)

All commands run from the agent's venv. Substitute the actual `HERMES_HOME` if it is not `/home/hermes/.hermes`.

```bash
# Search the default leads app by name or phone number
python3 ~/.hermes/skills/podio/podio_lookup.py --search "Devin Burchett"
python3 ~/.hermes/skills/podio/podio_lookup.py --search "+14059992900"

# List most-recent items in the default leads app
python3 ~/.hermes/skills/podio/podio_lookup.py --list-recent
python3 ~/.hermes/skills/podio/podio_lookup.py --list-recent --limit 20

# Target ANY app with --app (overrides PODIO_APP_ID)
python3 ~/.hermes/skills/podio/podio_lookup.py --app 12345678 --list-recent
python3 ~/.hermes/skills/podio/podio_lookup.py --app 12345678 --search "Acme"

# Read a single item fully (all field values, title, comment count, link).
# Works for an item in any app; no --app needed (the item knows its app).
python3 ~/.hermes/skills/podio/podio_lookup.py --get-item 3303283090

# Discover apps (and their app IDs) available in the workspace/org
python3 ~/.hermes/skills/podio/podio_lookup.py --list-apps

# JSON output (for piping into other tools), works on any read command
python3 ~/.hermes/skills/podio/podio_lookup.py --search "Devin" --json
python3 ~/.hermes/skills/podio/podio_lookup.py --app 12345678 --get-item 999 --json

# Legacy convenience: set the Invoice Status category on a default-app item
python3 ~/.hermes/skills/podio/podio_lookup.py --update-status 3303283090 "Invoice Sent"
```

Notes on reads:

- For the default leads app, results are printed with the known leads fields (name, phone, email, job, date, status). For any other app, results are printed generically: every populated field is shown by its label, plus the item ID and link.
- `--list-apps` is the way to find an app ID before using `--app` or `create-item`.
- Valid statuses for the legacy `--update-status`: `New Lead`, `Quoted`, `Invoice Sent`, `Invoice Paid`, `Cancelled`. This flag only targets the default leads app's Invoice Status field. For category fields on other apps, use `podio_write.py update-item` instead.

## Write commands (`podio_write.py`)

```bash
# Create an item. --app is required (find it with --list-apps).
# --field repeats; values are coerced to the right Podio shape per field type.
python3 ~/.hermes/skills/podio/podio_write.py create-item --app 12345678 \
    --field title="Acme Roofing" \
    --field phone=+14055551234 \
    --field email=owner@acme.com \
    --field status="New Lead"

# Or pass a full field map as JSON
python3 ~/.hermes/skills/podio/podio_write.py create-item --app 12345678 \
    --json '{"title":"Acme Roofing","status":"New Lead"}'

# Update field values on an existing item (the app is read from the item)
python3 ~/.hermes/skills/podio/podio_write.py update-item 3303283090 \
    --field status="Invoice Sent"
python3 ~/.hermes/skills/podio/podio_write.py update-item 3303283090 \
    --json '{"status":"Quoted","amount":1200}'

# Add a comment to an item
python3 ~/.hermes/skills/podio/podio_write.py comment 3303283090 \
    "Invoice emailed to the owner"

# Create a task, optionally linked to an item, optionally with a due date
python3 ~/.hermes/skills/podio/podio_write.py task "Call Acme back"
python3 ~/.hermes/skills/podio/podio_write.py task "Follow up with Acme" \
    --item 3303283090 --due 2026-07-01

# Mark a task complete
python3 ~/.hermes/skills/podio/podio_write.py complete-task 987654321

# Add --json-out to any write command for the full Podio response object
python3 ~/.hermes/skills/podio/podio_write.py create-item --app 12345678 \
    --field title="Acme" --json-out
```

## Field value gotchas

Podio fields are not addressed by display label in the API. Each field has an `external_id` (a stable, human-readable slug like `title` or `phone`) and a numeric `field_id`. Address fields by their `external_id` when writing. Find a field's external_id by reading any item in that app with `--get-item ... --json` (the JSON shows each field's `external_id`, `field_id`, `label`, and `type`).

Field VALUES are type-specific shapes. For `create-item` / `update-item`, the writer fetches the app config once (`GET /app/{app_id}`) to learn each field's type and category options, then coerces your `--field key=value` input automatically:

- **text / number / money**: the value is passed through as a string or number.
- **phone / email**: wrapped as `[{"type":"other","value":"<value>"}]`. (Podio phone/email fields are multi-value with a subtype; `other` is a safe default. If you need a specific subtype like `mobile` or `work`, pass the full shape via `--json`.)
- **date**: sent as `{"start":"YYYY-MM-DD"}`. A full `YYYY-MM-DD HH:MM:SS` start is also accepted.
- **category / status / state**: take an option ID, not the raw label, in the API. The writer accepts EITHER the label (case-insensitive, resolved against the app's options) OR a literal numeric option ID. If you pass a label that does not exist, it lists the valid labels and exits 1.
- **app reference / contact / member**: pass the referenced item ID / profile ID. A bare numeric `--field ref=123` is coerced to an integer; for multi-reference or complex shapes use `--json`.

When you pass `--json`, bare scalar values for known fields are still coerced (so `{"status":"New Lead"}` resolves the category label), but any value you supply as an object or list is trusted as-is. Use `--json` when you need full control over a value's shape.

## Example workflows

Discover an app, read it, then write to it:

```bash
# 1. Find the app you want
python3 ~/.hermes/skills/podio/podio_lookup.py --list-apps
# 2. Inspect one item to learn field external_ids and types
python3 ~/.hermes/skills/podio/podio_lookup.py --app 12345678 --list-recent --limit 1 --json
# 3. Create a new item
python3 ~/.hermes/skills/podio/podio_write.py create-item --app 12345678 \
    --field title="New Deal" --field stage="Prospecting"
# 4. Move it forward and leave a note
python3 ~/.hermes/skills/podio/podio_write.py update-item <new_item_id> --field stage="Negotiation"
python3 ~/.hermes/skills/podio/podio_write.py comment <new_item_id> "Sent the proposal today"
# 5. Schedule the follow-up
python3 ~/.hermes/skills/podio/podio_write.py task "Follow up on proposal" \
    --item <new_item_id> --due 2026-07-01
```

## How this skill chains

- **QBO invoicing** (`skills/qbo-invoicing/`): pass `--podio-item-id ITEM_ID` to `create_invoice.py` so the lead status flips to "Invoice Sent" after the invoice is created. The QBO skill calls the Podio API inline (not by importing these scripts) to avoid a circular dependency.
- **Payment checks** (`skills/qbo-invoicing/check_payments.py`): polls QBO for paid invoices and updates matching Podio items to "Invoice Paid".

## Troubleshooting

- **"Auth failed (401): expired_token"**: should never reach the user because the scripts auto-refresh and retry once. If it persists, the refresh token in the `.env` is broken: trigger a fresh credential sync from NoDesk (admin panel, Re-sync) or have the customer re-OAuth Podio.
- **Writer exits with code 2**: no access token is available (`PODIO_ACCESS_TOKEN` missing). The customer has not connected Podio, or the sync did not deliver the token. Reconnect Podio in the portal.
- **"is not a valid option for this category field"**: the label you passed does not match the app's category options. The error lists the valid labels. Pass one of those (or the numeric option ID).
- **"PODIO_APP_ID is 0" or default reads return nothing**: the default leads app is not configured. Use `--list-apps` to find the right app ID and pass it with `--app`, or have the customer paste an app ID on the connect portal.
- **A write succeeds but a field did not change**: confirm you used the field's `external_id` (not its display label). Read the item with `--get-item ... --json` to see the correct external_ids and types.
