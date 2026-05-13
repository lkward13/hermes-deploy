# Polling Pitfalls

## Missed-reply failure mode
The cron runner originally checked active leads with `check_sms.py --since 2`, which can miss inbound replies that arrive between one-minute cron ticks or when the poll fires slightly late.

## Safer pattern
- Use a wider lookback window for SMS polling (10 minutes is a safer default here).
- Deduplicate using lead conversation history / timestamps, not a tiny lookback window.
- If possible, prefer a true inbound webhook trigger over polling for near-real-time replies.

## Symptom
A lead reply exists in ClickSend history, but the automation logs show:
- `script produced no output, skipping AI call`
- `agent returned [SILENT]`

That means the poll likely missed the reply rather than the lead failing to answer.
