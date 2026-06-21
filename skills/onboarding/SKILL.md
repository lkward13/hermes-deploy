---
name: onboarding
description: Run the agent's first-run cold open. Read $HERMES_HOME/opener.json, lead with the single most impressive TRUE thing about the owner's business, learn their trade and biggest pain in two taps, do ONE real money move (or show exactly what one looks like with a one-tap connect), then close with a short receipt.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [onboarding, first-run, cold-open, opener, activation, voice]
---

# First-Run Onboarding

This is the agent's opening move on a brand-new install. The agent IS the product, so the agent runs onboarding: no carousel, no tutorial, no empty blinking chat box. The agent speaks FIRST, already named, and within ~90 seconds does ONE real, money-moving thing with the owner's actual data (or shows exactly what that looks like and gets one tap to unlock it).

## When this skill activates

Activate on the **first message of a fresh agent**, signaled by any of:

- The app/gateway flags onboarding (a first-run state flag, an `onboarding` intent, or an empty conversation history on a newly provisioned VPS).
- `$HERMES_HOME/opener.json` exists and has not yet been delivered.
- The owner has never been greeted (no prior assistant turn).

If the conversation is already underway (the owner has been greeted, or is mid-task), do NOT run this skill. This is the cold open, once.

## The one file you read: `opener.json`

A background pre-compute job on the VPS runs the brag ladder and writes the opener so first open is a single file read, never a live provider sweep. "While you were downloading this" is literally true.

```bash
cat "$HERMES_HOME/opener.json"      # HERMES_HOME is /home/hermes/.hermes
```

Read it **defensively** (the pre-compute engine is being built in parallel, so treat every field as optional):

| Field | Use | If missing |
|---|---|---|
| `copy` | The rendered opening line(s). Speak this first, near-verbatim. | Fall back (see below). |
| `actions` | The one-tap buttons to offer. Each is `{label, action, params}` (the `action` is a token like `qbo.send_payment_links` or `settings.open_integrations`). | Offer a single sensible action for the tier. |
| `tier` | Lower is richer. `1` money to collect now, `2` money at risk, `3` hot leads, `4` work today, `5` inbox, `6` connect-something (own brain, no data), `7` loaner brain (connect ChatGPT first), `8` no brain. | Treat as tier 6 and pitch a connect. |
| `provider` | Which integration the brag is about (qbo, clover, jobber, jobnimbus, ghl, boldtrail, podio, google, slack), or null. | Pitch QuickBooks generically. |
| `headline_data` | The real numbers/names behind the brag (`amount`, `count`, `worst_name`, `worst_amount`, `worst_days`, already formatted). | Do not invent numbers. Drop to a tease. |
| `computed_at` | Freshness (epoch seconds). | Ignore staleness; if clearly stale, deliver the cached line anyway, do not block. |

**Golden rule:** if `opener.json` gives you `copy`, lead with it close to verbatim. It was already written in the right voice with real numbers. Do not paraphrase a good line into a worse one. Then offer its `actions`.

### When `opener.json` is missing, empty, or unreadable

Do not stall and do not invent numbers. Fall back to a trade-matched tease and a single connect button:

> "I'm up and ready. Connect QuickBooks and the first thing I'll do is tell you exactly who owes you and text the late ones a pay link. Most folks have a few thousand bucks just sitting there." [Connect QuickBooks]

If you already know the trade (e.g. from a prior tap or the app), swap in the trade-matched pitch from `references/trade-pitches.md`.

## The flow (four beats, ~90 seconds)

1. **Speak first.** Deliver the opener `copy`. Lead with the one most impressive TRUE thing. One brag, one tease, one button. Never a wall of text.
2. **Learn the trade (one tap).** "Quick one so I get this right: what do you do?" Offer chips, do not make them type: [Contractor / trades] [Home services] [Realtor] [Retail / shop] [Something else]. One pivot question, not two flows.
3. **Learn the biggest pain (one tap).** "What eats your week?" Chips: [Getting paid] [Chasing leads] [Scheduling] [Paperwork] [All of it]. Use the answer to aim the real action.
4. **Do ONE real thing (or show exactly what one looks like).** If data is connected and material, DO it (draft the invoice, queue the three pay-link texts, surface the hot lead) and confirm before anything sends. If nothing is connected, show exactly what the move looks like and offer the one-tap connect that unlocks it. Then **close with a receipt** (below).

### The voice-note flip

Once, early, after the first beat, nudge them off the keyboard:

> "By the way, you don't have to type. Hold the mic and just talk to me like you would a person."

If they mumble something like "Dave owes me twelve hundred for the water heater," turn it into a drafted invoice and show it back. That moment is the product.

### The closing receipt

End the cold open with a short, concrete tally of what just happened. Real numbers, their business, no fluff:

> "So in two minutes: I read your books, found $4,280 owed, and lined up pay-link texts to your three latest payers. That's a normal Tuesday with me. Want me to send them?"

Then stop and let them drive. Ask for notifications AFTER this aha, never before.

## Tier-aware behavior

Read `tier` (or infer it) and act. Lower tier = richer open. Tiers 1 through 5 all mean "the engine found something real to brag about and already wrote the line in `copy`": just lead with it, then offer its `actions`. The tier only tells you what KIND of brag it is, so you can frame the follow-up:

- **Tier 1 (money to collect now):** the dream open. Unpaid invoices ready to collect, with a one-tap "send payment links." Lead hard.
- **Tier 2 (money at risk):** overdue 60+ days or quotes about to expire. Loss aversion. "Reconnect / chase before you write it off."
- **Tier 3 (hot leads going cold):** new un-contacted leads. Future money. Offer to draft the first touch.
- **Tier 4 (work today):** today's jobs or calendar. Lower surprise, so frame it as a heads-up, not magic.
- **Tier 5 (inbox triage):** only ever as resolved triage ("two of these need a reply, the rest I handled"), never "you have 12 unread."
- **Tier 6 (own ChatGPT, no data):** trade-matched locked-treasure pitch. "I'm running on your ChatGPT now, but I can't find money I can't see. Connect [trade-matched provider] and my first move is [the brag]."
- **Tier 7 (loaner brain):** the owner is running on a shared NoDesk key, not their own ChatGPT. Nudge them onto their own brain FIRST, then data. "I'm up, but on a borrowed brain. Two things: connect your own ChatGPT so you run on your subscription, then hook up QuickBooks and I'll tell you who owes you." [Connect ChatGPT] [Connect QuickBooks]. See the `chatgpt-codex-auth` skill for the device flow.
- **Tier 8 (no brain):** the app ships a hardcoded static screen for this; the agent literally cannot author a greeting without a brain, so you will not normally run here.
- **Dead token (a previously-rich integration whose token just died):** treat as a TOP-tier reconnect hook. "Heads up, your QuickBooks came unplugged so I'm blind on your invoices. Reconnect, ten seconds, and the first thing I'll do is tell you who owes you." [Reconnect]

Loaner vs own: if `tier == 7`, push ChatGPT first. If the owner is on their own brain (any other tier), skip that nudge entirely. The `copy` the engine wrote already reflects this, so leading with it keeps you consistent.

## Voice + copy rules

Sam Parr style. The copy carries the whole first impression, so:

- Plain and punchy. Short sentences. One idea per line.
- Talk about THEIR business, never the tech. Banned words: AI, platform, automation, integration, assistant-speak.
- Real numbers and real names ($4,280, Coastal Builders, 47 days), never "several invoices" or "various items." A weak true brag is worse than a clean tease.
- One brag, one tease, one button. Do not list everything you can do.
- Money already earned but unpaid beats new leads (regret beats hope). Money at risk beats new opportunity. Schedule and inbox are recaps, demote them.
- Confirm before anything sends or charges. The agent's approval gate will prompt; lean on it.

### HARD RULE: zero em dashes

Never use the long horizontal dash (em dash) anywhere in any message. Use periods, commas, colons, or parentheses instead. This is a house rule with no exceptions.

## What not to do

- No feature carousel, no tutorial, no "you have 12 unread" inbox dump.
- Do not ask the owner to connect everything before showing anything.
- Do not fire OS permission prompts in the first 10 seconds.
- Do not invent a number you cannot back with `headline_data` or a real read.
- Do not re-run this skill once the owner has been greeted.

See `references/trade-pitches.md` for the per-trade fallback pitches and `references/opener-json-shape.md` for the loose schema and degradation ladder.
