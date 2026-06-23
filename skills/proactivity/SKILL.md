---
name: proactivity
description: Manage the owner's proactive nudges (the "HEADS UP" reminders about new leads, overdue invoices, etc.). Use this whenever the owner responds to a proactive nudge, especially to snooze it, mark it done, or say they already handled it.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [proactivity, nudges, reminders, leads, snooze, done]
---

# Proactive nudges: managing them

The agent proactively pings the owner about money and hot leads (new uncontacted
leads, overdue invoices, etc.). Those "HEADS UP" messages are sent by a
background tick, not by you in the moment. Each nudge that the owner can manage
ends with two tappable chips:

- **"Done, stop reminding me"**
- **"Snooze 1 day"**

When the owner taps one of these (or otherwise tells you they already handled a
lead, or to stop reminding them about it, or to remind them later), you must
record it so the engine stops re-surfacing that lead. This is deterministic, not
a promise you keep in your head.

## How to dismiss

Run, from `$HERMES_HOME/hermes-agent`:

```bash
# Owner tapped "Done, stop reminding me" (or said they handled it / stop nagging):
./venv/bin/python -m hermes_cli.nodesk_proactivity dismiss \
    --provider <podio|boldtrail|gohighlevel> --name "<lead name>" --done

# Owner tapped "Snooze 1 day" (or "remind me tomorrow / later"):
./venv/bin/python -m hermes_cli.nodesk_proactivity dismiss \
    --provider <podio|boldtrail|gohighlevel> --name "<lead name>" --snooze 24
```

- `--provider` and `--name` come straight from the nudge you are responding to
  (e.g. "Dickenson Larry came in ... on **Podio**" -> `--provider podio --name "Dickenson Larry"`).
- `--snooze` takes hours; 24 = one day. Use a different number if the owner asks
  ("snooze a week" -> `--snooze 168`).
- It prints `{"ok": true, ...}`. Then confirm briefly, e.g. "Got it, I will not
  remind you about Dickenson Larry again." (for Done) or "Okay, I will hold off
  on that one for a day." (for Snooze).

## Which lead

The chip the owner tapped applies to the lead(s) in the nudge message it was
attached to. If that message named one lead, dismiss that one. If it named
several and the owner did not single one out, ask which, or dismiss all of them
if they said "all" / "these" / "all of them".

## Notes

- **Done is forever**; **Snooze is temporary** (the lead can resurface after the
  window if still unhandled). Pick the one the owner asked for.
- You never need to dismiss to STOP a one-time nudge: the engine already nudges
  each new lead only once. Dismiss is for when the owner wants a specific lead
  silenced for good, or pushed out.
- For a precise dismissal you can pass `--entity <entity_id>` instead of
  provider+name, but provider+name (from the nudge) is the normal path.
