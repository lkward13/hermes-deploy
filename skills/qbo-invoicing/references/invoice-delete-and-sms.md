# Invoice Delete + SMS Delivery Notes

## Hard delete test invoices
QBO supports hard-deleting transaction entities like invoices.

Use the simplified delete request:

```bash
POST /v3/company/{realmId}/invoice?operation=delete
```

Body:
```json
{
  "Id": "7",
  "SyncToken": "0"
}
```

Observed result:
- `200 OK`
- Response shape: `{"Invoice":{"domain":"QBO","status":"Deleted","Id":"7"}}`
- A subsequent `GET /invoice/7` may return `400 Bad Request` because the invoice is gone.

## SMS delivery caveat
The invoicing script’s `SMS sent: SUCCESS` output only means ClickSend accepted the message request. It is not an end-user delivery confirmation.

If the recipient says they did not receive the text:
1. Verify the invoice and payment link still exist.
2. Send the payment link directly with the standalone SMS sender.
3. Treat the direct sender’s success status as an API accept signal, not proof of handset delivery.

## Practical fallback
For invoice-link texts, a direct resend like this is a reliable fallback:

```bash
cd ~/.hermes/skills/lead-auto-text
python3 send_sms.py --to +1XXXXXXXXXX --body "Here’s your invoice: <payment link>"
```

## Verification notes
- If a hard delete succeeds, do not keep retrying the invoice lookup.
- If the recipient still does not get the SMS after a resend, suspect carrier filtering or sender-number blocking rather than invoice creation failure.
