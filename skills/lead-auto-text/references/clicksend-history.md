# ClickSend SMS history retrieval

Use this when webhook/polling context is incomplete or you need to verify recent inbound/outbound SMS bodies before replying.

## Endpoints
- `GET /v3/sms/history` — view SMS history with filters
- `GET /v3/sms/history/export` — export the same view as CSV

## Useful filters
- `q=status:Received` — inbound messages
- `q=from:%2B1XXXXXXXXXX` — filter by sender number (URL-encode `+`)
- `order_by=date:desc` — newest first
- `date_from` / `date_to` — Unix timestamps for a bounded lookback

## Notes
- The API uses Basic Auth.
- Exported CSV is often the easiest way to inspect the exact message bodies in order.
- Use a wider lookback when checking replies so multi-part or rapid-fire messages are not missed.
- This is especially useful when owner approval replies or a lead’s follow-up arrive close together and `check_sms.py` returns nothing.