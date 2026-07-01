---
name: lead-auto-text
description: "Auto-text new leads from any connected source and engage them conversationally to set owner-approved appointments."
version: 2.0.0
author: NoDesk
metadata:
  hermes:
    tags: [SMS, Leads, Sales, Appointments, SpeedToLead]
---

# Lead Auto-Text

Automatically text new leads the instant they arrive, engage naturally, and guide
qualified leads toward owner-approved appointments. **Speed is the whole game** —
the first text should go out within seconds of a lead landing.

Intake is **source-agnostic**: every connected source (Facebook, Jobber,
GoHighLevel, BoldTrail, Podio, website forms, CallRail, manual entry) funnels
into the NoDesk gateway's canonical lead queue. This skill polls that one queue,
so the conversation engine never cares where a lead came from. SMS runs through
ClickSend.

## Delegation Rule

The main Hermes agent should delegate lead conversations to the configured lead
specialist (`AGENT_SUBAGENT_NAME`). The specialist texts new leads, replies to
inbound messages, maintains lead state, and escalates appointments to the
business owner/admin for approval.

## Runtime Context

Reads from `$HOME/.hermes/.env`:

- `BUSINESS_NAME`, `OWNER_NAME`, `OWNER_PHONE`, `ADMIN_NAME`, `ADMIN_PHONE`, `AGENT_SUBAGENT_NAME`
- `CLICKSEND_USERNAME`, `CLICKSEND_API_KEY`, `CLICKSEND_FROM`
- `NODESK_BASE_URL`, `HERMES_CLIENT_ID` — used to poll/mark the gateway lead queue
- `HERMES_TIMEZONE` — tenant timezone for quiet-hours (falls back to UTC if unset)
- Optional: `LEAD_TEXT_START_HOUR` (default 8), `LEAD_TEXT_END_HOUR` (default 21)

## Engine Loop (per poll)

1. `python3 poll_leads.py` → returns `new_leads[]` (each: `lead_id, source, name,
   phone, email, address, service_type, message, received_at`). Reading the queue
   **claims** the leads, so they're handed out exactly once.
2. For each new lead, **immediately** persist it locally before texting
   (write-ahead — survives a crash): `lead_state.py add --name ... --phone ...
   --source <source> --lead-id <lead_id>`.
3. Send the first text (see Conversation Rules). Log every message with
   `lead_state.py log-message`.
4. On each subsequent tick, check replies with `check_sms.py` and continue the
   conversation per state.
5. When a lead reaches a terminal state, report it back so the queue and
   analytics stay accurate: `python3 mark_lead.py --lead-id <id> --status
   done|declined|opted_out|unresponsive`.

## Conversation Rules

- **Be fast.** First text within seconds of the lead arriving.
- Personalize: use the lead's name and reference what they actually asked about
  (`service_type` / `message`). Keep texts short, natural, professional.
- Introduce the specialist and business in the first message.
- Do not oversell or pressure.
- **No pricing.** Do not give prices, estimates, ranges, or ballparks unless the
  client is explicitly configured for it. If asked about price, explain that every
  project is different and the owner needs to see the job to quote accurately.
- **Never confirm appointments without owner/admin approval** (see Scheduling).
- On STOP/UNSUBSCRIBE: stop immediately and `mark_lead.py --status opted_out`.

## Quiet Hours (lead-facing texts only)

Before sending a **lead-facing** text, respect the tenant's local texting window.
Either check first — `python3 quiet_hours.py` (returns `{"ok": ...,
"next_ok_local": ...}`) — or let `send_sms.py` enforce it mechanically:

```bash
python3 send_sms.py --to +1XXXXXXXXXX --body "message" --respect-quiet-hours
```

If it's quiet hours, the send is refused (exit 2) and you should defer the text to
`next_ok_local`. **Owner/admin notifications are exempt** — send those WITHOUT
`--respect-quiet-hours` so urgent approvals always go through.

## Scheduling Flow

1. When a lead asks to schedule, update them to `pending_approval`.
2. Text the configured owner/admin (no quiet-hours flag) with name, phone,
   requested time, project details, and a conversation summary.
3. Ask for `YES` or `NO`.
4. On `YES`, confirm with the lead, then `mark_lead.py --status done`.
5. On `NO`, ask the lead for alternatives.

## Helper Scripts

```bash
python3 poll_leads.py                  # poll the gateway queue (claims leads)
python3 poll_leads.py --no-claim       # peek without claiming (testing)
python3 send_sms.py --to +1XXXXXXXXXX --body "msg" [--respect-quiet-hours]
python3 check_sms.py --from +1XXXXXXXXXX --since 60
python3 quiet_hours.py                  # {"ok": bool, "next_ok_local": ...}
python3 mark_lead.py --lead-id <id> --status done|declined|opted_out|unresponsive
python3 lead_state.py add --name "John Smith" --phone +1XXXXXXXXXX --email j@x.com --source website --lead-id <id>
python3 lead_state.py update --phone +1XXXXXXXXXX --status in_conversation
python3 lead_state.py log-message --phone +1XXXXXXXXXX --direction outbound --body "Hey John!"
```
