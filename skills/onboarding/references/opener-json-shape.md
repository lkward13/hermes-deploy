# `opener.json` shape (loose, defensive)

The opener pre-compute job writes `$HERMES_HOME/opener.json` on provision, on every connect/disconnect, on token refresh, and on a light schedule. The agent reads it once at first open. The schema below is the intended shape, but the engine is being built in parallel, so **treat every field as optional and degrade gracefully**. Never crash or stall on a missing field, and never invent a number you cannot back.

## Intended shape

This is the actual shape the engine (`hermes_cli/nodesk_opener.py`) writes. Read it defensively anyway.

```json
{
  "tier": 1,
  "provider": "qbo",
  "copy": "You have $4,280 in unpaid invoices ready to collect. That is 3 invoices, the biggest is $1,900 from Coastal Builders. Want me to send a payment link to all 3 right now?",
  "actions": [
    { "label": "Send payment links", "action": "qbo.send_payment_links", "params": { "provider": "qbo", "count": 3 } }
  ],
  "headline_data": {
    "amount": "$4,280.00",
    "count": 3,
    "provider_label": "QuickBooks",
    "worst_amount": "$1,900.00",
    "worst_name": "Coastal Builders",
    "worst_days": 47
  },
  "trade": "plumber",
  "computed_at": 1750430580,
  "version": 1
}
```

## Field handling

- **`copy`** is the load-bearing field. If present, speak it near-verbatim. If absent, fall back to a trade-matched pitch (`trade-pitches.md`).
- **`actions`** maps to one-tap buttons. Each is `{label, action, params}`. The `action` is a token: `settings.*` tokens (e.g. `settings.open_integrations`, `settings.connect_chatgpt`) are app deep links; the rest (`qbo.send_payment_links`, `invoices.chase_overdue`, `leads.draft_first_touch`, `calendar.show_run_sheet`, `inbox.triage`) are intents you run via the matching skill. Read field names loosely. If absent, offer one sensible action for the tier.
- **`tier`** drives the ladder (below). **Lower is richer.** If absent, infer from what is connected; default to tier 6 (own brain, no data, pitch a connect).
- **`provider`** names the integration the brag is about (or null). There is no separate `brain` field: a loaner brain is signaled by `tier == 7`, no brain by `tier == 8`.
- **`headline_data`** backs the brag with real values (`amount`, `count`, `worst_name`, `worst_amount`, `worst_days`, all pre-formatted). If absent, drop from a brag to a tease (no specific number).
- **`computed_at`** is epoch seconds (freshness). If clearly stale, still deliver the cached copy immediately, do not block on a live refresh.

## Degradation ladder (tiers, lower is richer)

| Tier | State | Move |
|---|---|---|
| 1 | Money to collect now | Lead hard: the brag + one-tap send-pay-links. |
| 2 | Money at risk (60+ overdue, expiring quotes) | Loss aversion: chase before it is written off. |
| 3 | Hot leads going cold | Offer to draft the first touch. |
| 4 | Work about to happen (schedule/calendar) | Heads-up, not magic. |
| 5 | Inbox triage | Resolved triage only, never an unread dump. |
| 6 | Own ChatGPT, no data | Trade-matched locked-treasure pitch. |
| 7 | Loaner brain | Connect your own ChatGPT first, then data. |
| 8 | No brain | App ships a static screen; agent cannot author a greeting. |
| - | Dead token | Reconnect hook, treated as top-tier. |

For tiers 1 through 5 the engine has already written `copy` in the right voice with real numbers, so lead with it; the tier just tells you what kind of brag it is.

## Assumptions to verify with the pre-compute team

- Field names are now locked against the engine (`copy`, `actions[].action`, `tier`, `provider`, `headline_data`, `computed_at`, `version`). If the engine changes, re-sync this doc.
- How "first run" is signaled to the agent (first-run flag, empty history, `onboarding` intent, or the mere presence of an undelivered `opener.json`). The skill checks several signals; confirm which one the app actually sends.
- Whether the agent is expected to mark the opener delivered (e.g. delete or stamp `opener.json`) so it does not re-fire. Currently the skill relies on the greeted/empty-history check; confirm the dedupe owner.
- Whether `actions` carry executable intents the agent runs directly, or are app-side deep links. The skill offers them as one-tap buttons either way.
