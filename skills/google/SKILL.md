# Google Skill (Gmail + Calendar)

Provides CLI access to Gmail and Google Calendar via OAuth tokens synced from NoDesk.

## Auth

Tokens come from the agent's `.env`:
- `GOOGLE_ACCESS_TOKEN` — refreshed automatically on each call
- `GOOGLE_REFRESH_TOKEN` — long-lived, used to get new access tokens
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — NoDesk app credentials

All scripts import `google_auth.py` which handles refresh transparently. No manual token management needed.

## Gmail

```bash
cd /root/.hermes/skills/google

# Send an email
python gmail.py send --to "client@example.com" --subject "Invoice Ready" --body "Your invoice is attached."

# List recent emails (default 10)
python gmail.py list
python gmail.py list --max 20 --query "is:unread"
python gmail.py list --query "from:client@example.com"

# Read a specific email
python gmail.py read --id <message_id>
```

Output is JSON. `list` returns array of `{id, from, subject, date, snippet}`. `read` returns full body (truncated at 4000 chars).

## Calendar

```bash
cd /root/.hermes/skills/google

# List upcoming events (default 7 days)
python calendar.py list
python calendar.py list --days 14 --max 30

# Create an event
python calendar.py create \
  --title "Client Call" \
  --start "2026-05-20T10:00:00" \
  --end "2026-05-20T11:00:00" \
  --description "Discuss quote approval" \
  --attendees "client@example.com,partner@example.com"

# Delete an event
python calendar.py delete --id <event_id>
```

Timezone defaults to America/Chicago. Adjust in calendar.py if needed.

## Notes

- Gmail scope: send + readonly. Cannot delete emails.
- Calendar scope: full read/write on primary calendar.
- The client must connect Google in their NoDesk portal for tokens to be present.
- If tokens are missing, scripts exit with a clear error message.
