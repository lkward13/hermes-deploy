# ClickSend inbound webhook notes

Session takeaway: inbound SMS replies for `lead-auto-text` are handled by the ClickSend webhook route, not by cron polling.

## What changed
- Cron no longer polls `check_sms.py --since 2` for replies.
- Cron is now limited to discovering new Facebook leads.
- Inbound replies arrive on the gateway webhook route, bound on `0.0.0.0:8644`.

## Authentication = the route NAME (capability URL)
ClickSend cannot attach a custom header or sign its webhooks, so the per-route
`secret` stays `INSECURE_NO_AUTH` (the header-HMAC check is skipped). Auth is
instead the **unguessable route name**: NoDesk renders a per-tenant secret into
`HERMES_WEBHOOK_ROUTE` (e.g. `clicksend-sms-<secret>`) and points the ClickSend
inbound rule at `/webhooks/<that name>`. The gateway returns **404 on any
unknown route name**, so a wrong/missing secret is rejected without confirming
the endpoint exists. Rotating = NoDesk regenerates the secret, re-points the
ClickSend rule, and the next credential sync re-renders the route.

`webhook_subscriptions.json` is rendered from a template with TWO keys —
`{{HERMES_WEBHOOK_ROUTE}}` and `{{HERMES_WEBHOOK_ROUTE_LEGACY}}`. In warn mode
they render to different names (secret + bare `clicksend-sms`) so the ClickSend
rule can be cut over with no 404 window; at enforce they render equal and
JSON-collapse to a single secret route, dropping the bare one. Keep the two
template entries identical except for the key.

## Operational notes
- Confirm `HERMES_WEBHOOK_ROUTE` in `.env` matches the path in the ClickSend
  inbound rule. A mismatch shows up as `404 Unknown route` (not `401`).
- Per-user chat behaviour and the `lead-auto-text` flow are unchanged.

## Verification hints
- Look for successful `POST /webhooks/<route>` responses.
- `404 Unknown route` on the webhook port = the ClickSend rule URL and the
  rendered route name disagree (cutover ordering, or a stale on-box template).
- Confirm the webhook route produces a delegated Richard task and acquires/
  releases the lead lock.
- Avoid reintroducing reply polling unless webhook delivery is unavailable.
