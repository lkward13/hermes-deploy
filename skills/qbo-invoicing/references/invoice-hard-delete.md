# Invoice hard delete recipe

QBO invoices are transaction entities, so they support hard delete.

Observed working request:

- Method: `POST`
- URL: `/v3/company/{realm_id}/invoice?operation=delete`
- Body:

```json
{
  "Id": "7",
  "SyncToken": "0"
}
```

Example verification flow:
1. Read the invoice first to capture `Id` and `SyncToken`.
2. POST the delete request above.
3. Confirm the response shows `status: Deleted`.
4. A follow-up `GET /invoice/{id}` may return `400` once the record is gone.

Notes:
- This is a hard delete, not a void.
- Do not guess the SyncToken. Read it from the invoice record before deleting.
- Use this for test invoices only unless the user explicitly asks to remove a real invoice.
