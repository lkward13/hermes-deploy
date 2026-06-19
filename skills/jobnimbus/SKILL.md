---
name: jobnimbus
description: Read contacts, jobs, tasks, activities, estimates, and invoices from the customer's JobNimbus account via the JobNimbus Public API. Read-only — never writes.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [JobNimbus, CRM, contractor, roofing, jobs, contacts, leads, estimates, invoices]
---

# JobNimbus

Read data from the customer's JobNimbus account — the CRM/job-management system contractors (roofing, restoration, remodeling) run their business on. Authenticates via the API key NoDesk pushes to the agent's `.env` at credential-sync time.

**Read-only.** This skill only reads — it never creates or edits JobNimbus records.

## Authentication

Credentials live in `$HOME/.hermes/.env`:

- `JOBNIMBUS_API_KEY` — Bearer token. The customer generates it in JobNimbus → **Settings → API → New API Key**.

If `JOBNIMBUS_API_KEY` is empty, the customer hasn't connected JobNimbus yet — tell them to connect it in the NoDesk portal rather than asking for credentials. **Do NOT** look for `JOBNIMBUS_USERNAME` or `JOBNIMBUS_PASSWORD` — they don't exist.

## Commands

All commands run from the agent's venv. Add `--json` to any command for raw JSON output.

```bash
# Connectivity / key check (also returns account info)
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --account

# Contacts
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-contacts [--limit 25]
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --search "Smith"        # name / email / phone / company
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --get-contact JNID

# Jobs
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-jobs [--limit 25]
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --get-job JNID

# Tasks, activities (notes), financials
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-tasks [--limit 25]
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-activities [--limit 25]
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-estimates [--limit 25]
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-invoices [--limit 25]
```

### Advanced filtering

List commands accept a raw `--filter` (JobNimbus's ElasticSearch-style query, URL-passed as the `filter` param):

```bash
# Only contacts whose status is "Lead"
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-contacts \
  --filter '{"must":[{"term":{"status_name":"Lead"}}]}'
```

`--search` is the simpler everyday path — it pulls contacts and matches client-side across name, email, phone, and company, so you don't need to know the filter DSL.

## Common workflows

**"Do we have a contact for Jane Doe, and what's her latest job?"**
```bash
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --search "Jane Doe"   # get the JNID
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --get-contact JNID    # full detail
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-jobs --limit 25  # find her job
```

**"What jobs are open / what's on my plate?"**
```bash
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-jobs --limit 25
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-tasks --limit 25
```

**"How much have we estimated/invoiced lately?"**
```bash
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-estimates --limit 25
python3 ~/.hermes/skills/jobnimbus/jobnimbus_lookup.py --list-invoices --limit 25
```

## Notes

- Records are identified by a **JNID** (e.g. `abc123def...`), shown first in every list row. Pass it to `--get-contact` / `--get-job`.
- Dates in JobNimbus are Unix epoch timestamps; this skill renders them as `YYYY-MM-DD`.
- Lists are paginated by `--limit` (JobNimbus `size`, max 1000 per call).

## Troubleshooting

- **`JOBNIMBUS_API_KEY not set`** — customer hasn't connected JobNimbus; direct them to the NoDesk portal.
- **401** — API key invalid/revoked. Customer re-pastes a fresh key from JobNimbus → Settings → API; then trigger NoDesk credential sync.
- **403** — The key lacks permission for that resource (key scoped/limited in JobNimbus).
- **404** — Wrong JNID or the record doesn't exist.
- **429** — JobNimbus rate limit; wait a moment and retry.
