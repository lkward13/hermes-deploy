---
name: jobber
description: Run the customer's Jobber field-service account from chat: read clients, requests (leads), quotes, jobs, visits, invoices, and payments, and create clients, quotes, jobs, requests, and notes. GraphQL only, with a raw query/mutation passthrough and live schema introspection.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [Jobber, field-service, FSM, leads, quotes, jobs, scheduling, invoicing, GraphQL]
---

# Jobber

Read and write the customer's Jobber account (clients, requests/leads, quotes, jobs, visits, invoices, payments). Jobber exposes a single GraphQL endpoint, so this skill is built around two scripts plus universal escape hatches:

| Tool | What it does |
|---|---|
| `jobber_lookup.py` | Read: list connections, fetch a node, run any raw query, introspect the live schema (read-only) |
| `jobber_write.py` | Write: create client / quote / job / request / note, or run any raw mutation |

Both share one OAuth connection via `jobber_auth.py` (auto-refresh + GraphQL transport).

Run everything from the skill dir with the agent venv:

```bash
cd ~/.hermes/skills/jobber
source ~/.hermes/hermes-agent/venv/bin/activate
```

Add `--json` to any command for the raw GraphQL JSON.

## Authentication

Jobber is OAuth only. There is NO Jobber username or password. NoDesk pushes these to the agent's environment at credential-sync time; the scripts read them from `os.environ`:

- `JOBBER_ACCESS_TOKEN`: Bearer token (expires in about 60 minutes)
- `JOBBER_REFRESH_TOKEN`: long-lived refresh token
- `JOBBER_CLIENT_ID`, `JOBBER_CLIENT_SECRET`: app credentials (needed to refresh)
- `JOBBER_GRAPHQL_VERSION`: optional override of the pinned schema date

Because the access token expires after about an hour, the scripts self-refresh: on a 401 (or a `THROTTLED` / auth GraphQL error) they POST to `https://api.getjobber.com/api/oauth/token` with `grant_type=refresh_token`, cache the new access token to `jobber_tokens.json` (chmod 600) in the skill dir, and retry once. You do not manage tokens by hand.

If there is no access token AND no refresh token, the script exits 2 with a message to connect Jobber in the NoDesk portal.

Connectivity check: `python3 jobber_lookup.py account`.

### The GraphQL version header (important)

Every request sends `X-JOBBER-GRAPHQL-VERSION` (a date). This is REQUIRED by Jobber and pins the schema. The default is `2025-01-20`. This date may need updating over time. If you get a version or unknown-field error, run `jobber_lookup.py introspect` to see the live schema, and set `JOBBER_GRAPHQL_VERSION` to a newer date (in `~/.hermes/.env` or the environment).

The endpoint is `POST https://api.getjobber.com/api/graphql`. Responses put errors in a top-level `errors` array, and cost/throttle info in `extensions.cost` / `throttleStatus`. Connections are Relay-style (`first`, `after`, `edges { node }`, `pageInfo { hasNextPage endCursor }`). Rate limits: 2500 requests per 5 minutes (429), plus a query-cost leaky bucket, so keep queries shallow and paginated (the convenience commands already do).

---

# 1. Read: `jobber_lookup.py`

Read-only. Add `--json` for raw output.

```bash
python3 jobber_lookup.py account                          # connectivity + token check
python3 jobber_lookup.py clients [--search NAME] [--limit N]
python3 jobber_lookup.py requests [--limit N]             # leads
python3 jobber_lookup.py quotes [--limit N]
python3 jobber_lookup.py jobs [--limit N]
python3 jobber_lookup.py invoices [--limit N]             # who owes you
python3 jobber_lookup.py visits [--today] [--limit N]     # scheduling
python3 jobber_lookup.py schedule [--today] [--limit N]   # alias for visits
python3 jobber_lookup.py payments [--limit N]
python3 jobber_lookup.py get <Type> <id>                  # single node by id
```

`--limit` maps to the GraphQL `first` argument (capped at 100). `--after <cursor>` continues from a previous page's `pageInfo.endCursor`.

### Escape hatches (use these when a convenience field is off, or for anything not covered)

```bash
# Run any raw GraphQL query:
python3 jobber_lookup.py query 'query { account { id name } }'
python3 jobber_lookup.py query 'query($id:ID!){ client(id:$id){ name { full } } }' --vars '{"id":"Z2lk..."}'

# Discover the LIVE schema (the authoritative way to learn exact field names):
python3 jobber_lookup.py introspect                       # list root query + mutation field names
python3 jobber_lookup.py introspect Client                # list the Client type's fields
python3 jobber_lookup.py introspect QuoteCreateInput      # list an input type's fields
```

`introspect` is the agent's robustness lever: if a built-in selection or a documented field name does not match the live schema, introspect the type, then craft the exact query/mutation with the raw passthrough.

### Example reads

```bash
# Today's schedule (visits):
python3 jobber_lookup.py schedule --today

# Open quotes:
python3 jobber_lookup.py quotes --limit 50
# (filter to status with the raw query if needed, e.g. quoteStatus)

# Who owes me (invoices with a balance):
python3 jobber_lookup.py invoices --limit 50
# each row shows invoiceBalance; nonzero balances are outstanding

# A lead's contact info (find the request, then the client):
python3 jobber_lookup.py requests --limit 10
python3 jobber_lookup.py get Client <clientId>            # emails + phones
```

---

# 2. Write: `jobber_write.py`

The agent supplies the input object as JSON; the wrapper builds the documented mutation and surfaces `userErrors` (business validation) and top-level `errors` (schema/auth). Default output is a short result line; `--json` returns the full envelope.

```bash
python3 jobber_write.py create-client  '<json input>'
python3 jobber_write.py create-quote   '<json input>'
python3 jobber_write.py create-job     '<json input>'
python3 jobber_write.py create-request '<json input>'    # create a lead
python3 jobber_write.py note <Type> <id> "text"          # attach a note
python3 jobber_write.py mutation '<graphql>' [--vars '<json>']   # raw escape hatch
```

Pass `-` as the JSON argument to read it from stdin.

### Input recipes (verify field names with introspection if rejected)

```bash
# New client:
python3 jobber_write.py create-client '{"firstName":"Jane","lastName":"Doe","emails":[{"address":"jane@x.com","primary":true}],"phones":[{"number":"+14055551234","primary":true}]}'

# Quote for an existing client (get the clientId from `clients --search`):
python3 jobber_write.py create-quote '{"clientId":"Z2lk...","title":"Roof repair","lineItems":[{"name":"Roof repair","quantity":1,"unitPrice":1200}]}'

# Job:
python3 jobber_write.py create-job '{"clientId":"Z2lk...","title":"Spring cleanup"}'

# Request (lead):
python3 jobber_write.py create-request '{"clientId":"Z2lk...","title":"New lead from website"}'

# Note on a client:
python3 jobber_write.py note Client Z2lk... "Called, left voicemail"
```

If a create wrapper reports an unknown field or input error, introspect the input type and use the raw passthrough:

```bash
python3 jobber_lookup.py introspect QuoteCreateInput
python3 jobber_write.py mutation 'mutation($input:QuoteCreateInput!){ quoteCreate(input:$input){ quote{ id quoteNumber } userErrors{ message path } } }' --vars '{"input":{...}}'
```

> Creating records is a real write. Confirm details with the owner first; the agent's approval gate will prompt.

---

## Common workflows

"What's on the schedule today?" run `schedule --today`.

"Send a quote to Jane for $1,200." find her with `clients --search Jane` to get the `clientId`, then `create-quote '{"clientId":"...","lineItems":[{"name":"...","quantity":1,"unitPrice":1200}]}'`.

"Who owes me money?" run `invoices --limit 50` and read `invoiceBalance` (nonzero is outstanding); for precise filtering use a raw `query` on the `invoices` connection.

"Get me the contact info for this lead." run `requests` to find the lead, note its `client.id`, then `get Client <id>` for emails and phones.

"Log a new lead from the website." `create-request '{"clientId":"...","title":"Website lead"}'` (create the client first with `create-client` if they are new).

## Troubleshooting

- 401 Unauthorized (even after auto-refresh): the refresh failed. Tell the owner to reconnect Jobber in the NoDesk portal. Exits 3.
- Exit 2 ("connect Jobber in the NoDesk portal"): no access token and no refresh token in the environment. The customer has not connected Jobber.
- Version error or "unknown field" / "doesn't exist on type": the pinned schema date is stale or a field name drifted. Run `introspect` (and `introspect <Type>`) to see the live schema, then either fix the query with the raw passthrough or bump `JOBBER_GRAPHQL_VERSION` to a newer date.
- 429 Too Many Requests or `THROTTLED`: rate or cost limit hit (2500 req per 5 min, plus a query-cost bucket). Wait (honor any `Retry-After`) and retry, and keep queries shallow and paginated. Exits 5.
- `userErrors` in a write response: Jobber rejected the input (missing required field, bad reference). Read the message, fix the JSON (confirm ids with `jobber_lookup.py`), and retry.
- Bad JSON in an input or `--vars`: the script exits 1 with the parse error. Re-check quoting.
