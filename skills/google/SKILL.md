# Google Skill (Gmail + Calendar)

Provides CLI access to Gmail and Google Calendar via OAuth tokens synced from NoDesk.

## IMPORTANT: How to run these scripts

Always use the hermes venv Python to avoid stdlib naming conflicts:

```bash
VENV=/root/.hermes/hermes-agent/venv/bin/python3
```

Never use bare `python3` — it will fail with ImportError due to naming conflicts.

## Auth

Tokens come from the agent's `.env`:
- `GOOGLE_ACCESS_TOKEN` — refreshed automatically on each call
- `GOOGLE_REFRESH_TOKEN` — long-lived, used to get new access tokens
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — NoDesk app credentials

All scripts import `google_auth.py` which handles refresh transparently. No manual token management needed.

## Gmail

```bash
VENV=/root/.hermes/hermes-agent/venv/bin/python3

# Send an email
$VENV /root/.hermes/skills/google/gmail.py send --to "client@example.com" --subject "Invoice Ready" --body "Your invoice is attached."

# List recent emails (default 10)
$VENV /root/.hermes/skills/google/gmail.py list
$VENV /root/.hermes/skills/google/gmail.py list --max 20 --query "is:unread"
$VENV /root/.hermes/skills/google/gmail.py list --query "from:client@example.com"

# Read a specific email
$VENV /root/.hermes/skills/google/gmail.py read --id <message_id>
```

Output is JSON. `list` returns array of `{id, from, subject, date, snippet}`. `read` returns full body (truncated at 4000 chars).

## Calendar

```bash
VENV=/root/.hermes/hermes-agent/venv/bin/python3

# List upcoming events (default 7 days)
$VENV /root/.hermes/skills/google/gcalendar.py list
$VENV /root/.hermes/skills/google/gcalendar.py list --days 14 --max 30

# Create an event
$VENV /root/.hermes/skills/google/gcalendar.py create \
  --title "Client Call" \
  --start "2026-05-20T10:00:00" \
  --end "2026-05-20T11:00:00" \
  --description "Discuss quote approval" \
  --attendees "client@example.com,partner@example.com"

# Delete an event
$VENV /root/.hermes/skills/google/gcalendar.py delete --id <event_id>
```

Timezone defaults to America/Chicago.

## Notes

- Gmail scope: send + readonly. Cannot delete emails.
- Calendar scope: full read/write on primary calendar.
- The client must connect Google in their NoDesk portal for tokens to be present.
- If tokens are missing, scripts exit with a clear error message.
- calendar.py was renamed gcalendar.py to avoid shadowing Python's stdlib calendar module.
