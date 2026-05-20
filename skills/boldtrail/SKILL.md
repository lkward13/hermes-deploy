---
name: boldtrail
description: Search, create, and update contacts in the customer's BoldTrail real-estate CRM via the BoldTrail REST API. OAuth/API-token authenticated; no username/password.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [BoldTrail, CRM, real-estate, leads, contacts]
---

# BoldTrail

Read and write contacts in the customer's BoldTrail account. Authenticates via the API token NoDesk pushes to `~/.hermes/.env` as `BOLDTRAIL_API_TOKEN` (set when the customer connects on the connect portal). There is **no** username/password flow — do NOT check for `BOLDTRAIL_USERNAME` / `BOLDTRAIL_PASSWORD`. Those do not exist in this environment.

## Authentication

This skill reads credentials from `$HOME/.hermes/.env`:

- `BOLDTRAIL_API_TOKEN` (primary) — set by NoDesk's credential sync when the customer connects BoldTrail. This is a **JWT** issued by Inside Real Estate.
- `BOLDTRAIL_ACCESS_TOKEN` (fallback, same value — legacy duplicate)
- `BOLDTRAIL_API_BASE` (optional override) — defaults to `https://api.kvcore.com/v2/public`

BoldTrail is built on kvCORE under the hood (Inside Real Estate rebranded kvCORE → BoldTrail; the API host stayed `api.kvcore.com`). Auth header is always `Authorization: Bearer <JWT>`. Spec lives at https://developer.insiderealestate.com/publicv2/docs/api-standards.

## Commands

All commands run from the agent's venv. Substitute `HERMES_HOME` if it's not `/home/hermes/.hermes`.

### Search & read

```bash
# List most-recent contacts
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --list-recent
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --list-recent --limit 20

# Search by name, email, or phone (any field match)
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --search "Jane Doe"
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --search "+14059992900"
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --search jane@example.com

# Get one contact's full record
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py --get-contact 12345
```

### Create & update

```bash
# Create a new contact (name + at least one of email/phone)
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py \
  --create-contact \
  --name "Jane Doe" \
  --email jane@example.com \
  --phone "+14059992900" \
  --tag "buyer" --tag "qualified"

# Update fields on an existing contact (any combination)
python3 ~/.hermes/skills/boldtrail/boldtrail_lookup.py \
  --update-contact 12345 \
  --email new@example.com \
  --tag "investor"
```

### JSON output

Add `--json` to any command to get structured output instead of human-formatted text. Useful when piping into another script or when the LLM wants machine-readable results.

## Auth troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Error (401)` | API token missing / invalid / revoked | Customer regenerates via BoldTrail dashboard (Account → API Tokens), then re-pastes on `/connect/{token}` in the BoldTrail section of the NoDesk portal |
| `Error (404)` on a path | Endpoint shape may differ from default | Set `BOLDTRAIL_API_BASE` in `.env` to the correct base, or adjust the paths inside `boldtrail_lookup.py` |
| `Error (429)` | Rate limited | Script auto-retries with exponential backoff (1s, 2s, 4s). If it still fails, wait a minute and retry the command |
| `BOLDTRAIL_API_TOKEN not set` | Customer hasn't connected BoldTrail yet | Direct them to `/connect/{their-token}` and have them paste a BoldTrail API token in the BoldTrail section |

## How this chains with other skills

- **Podio** (`skills/podio/`): if the customer uses Podio as their primary lead pipeline, BoldTrail often holds the upstream lead data — you may need to read from BoldTrail and create/update Podio items. Both skills are CRM-style and use the same shape (search/list/create/update via CLI).
- **QBO invoicing** (`skills/qbo-invoicing/`): for closed deals, the BoldTrail contact's email + phone feeds straight into `create_invoice.py`'s `--customer`, `--email`, `--phone` flags.
- **lead-auto-text** (`skills/lead-auto-text/`): you can pipe `boldtrail_lookup.py --search QUERY --json` into the lead-auto-text flow to text a BoldTrail lead via ClickSend.

## Notes for the LLM

- The underlying API is kvCORE Public API V2. Endpoint shapes verified against the official docs at https://developer.insiderealestate.com/publicv2:
  - `GET /contacts?filter[<field>]=<value>` for search/list
  - `GET /contact/{id}` for one contact (note: **singular**, unlike list)
  - `POST /contact` to create
  - `PUT /contact/{id}` to update
- Known-good filter keys from the docs: `filter[email]`, `filter[registered_after]` (unix timestamp), `filter[assigned_agent_id]`, `filter[hashtags][]` (tags — repeat the param for multiple). For free-form name search the script tries `filter[name]`, `filter[first_name]`, and `filter[last_name]` in sequence and merges results.
- Pagination: `page` + `limit` params. Default `limit=100`, max `500`.
- Tags are called **hashtags** in kvCORE filters; the script sends both `hashtags` and `tags` keys on create/update so it survives either naming convention.
- BoldTrail/Inside Real Estate is reportedly building an MCP server. When it ships, this skill can be replaced by direct MCP tool calls; the SKILL.md will get updated then.
