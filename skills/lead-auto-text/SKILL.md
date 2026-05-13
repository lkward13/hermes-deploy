---
name: lead-auto-text
description: "Auto-text new Facebook leads and engage them conversationally to set appointments."
version: 1.1.0
author: NoDesk
metadata:
  hermes:
    tags: [SMS, Leads, Sales, Facebook, Appointments]
---

# Lead Auto-Text

Automatically text new Facebook leads, engage naturally, and guide qualified leads toward owner-approved appointments. SMS runs through ClickSend, and lead intake runs through Facebook Lead Ads.

## Delegation Rule

The main Hermes agent should delegate lead conversations to the configured lead specialist (`AGENT_SUBAGENT_NAME`). The specialist should text new leads, reply to inbound messages, maintain lead state, and escalate appointments to the business owner/admin for approval.

## Runtime Context

This skill reads business-specific behavior from `$HOME/.hermes/.env`:

- `BUSINESS_NAME`
- `OWNER_NAME`
- `OWNER_PHONE`
- `ADMIN_NAME`
- `ADMIN_PHONE`
- `AGENT_SUBAGENT_NAME`
- `CLICKSEND_USERNAME`
- `CLICKSEND_API_KEY`
- `CLICKSEND_FROM`
- `FB_PAGE_ACCESS_TOKEN`
- `FB_FORM_ID`

## Conversation Rules

- Keep texts short, natural, and professional.
- Introduce the specialist and business in the first message.
- Do not oversell or pressure.
- Do not give pricing, estimates, ranges, or ballparks unless explicitly configured for that client.
- If asked about price, explain that every project is different and the owner needs to see the job before quoting accurately.
- Never confirm appointments without owner/admin approval.

## Helper Scripts

```bash
python3 send_sms.py --to +1XXXXXXXXXX --body "message"
python3 check_sms.py --from +1XXXXXXXXXX --since 60
python3 lead_state.py lock --phone +1XXXXXXXXXX
python3 lead_state.py unlock --phone +1XXXXXXXXXX
python3 lead_state.py add --name "John Smith" --phone +1XXXXXXXXXX --email john@example.com --source facebook --fb-lead-id 123456
python3 lead_state.py update --phone +1XXXXXXXXXX --status in_conversation
python3 lead_state.py log-message --phone +1XXXXXXXXXX --direction outbound --body "Hey John!"
python3 poll_leads.py
```

## Scheduling Flow

1. When a lead asks to schedule, update them to `pending_approval`.
2. Text the configured owner/admin with name, phone, requested time, project details, and conversation summary.
3. Ask for `YES` or `NO`.
4. On `YES`, confirm with the lead.
5. On `NO`, ask the lead for alternatives.
