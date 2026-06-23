# AppFolio Owner Portal: authenticated JSON API

Observed from live owner-portal sessions. The Transactions/Statements pages
render only a React root, so the useful finance data comes from these JSON
endpoints called with the authenticated session cookies. Dates are MM/DD/YYYY.

Base: `https://<company>.appfolio.com`

## Endpoints

```text
GET /oportal/api/owner_ownerships
GET /oportal/api/owner_income_balances?start_on=MM/DD/YYYY&end_on=MM/DD/YYYY
GET /oportal/api/owner_expenses_balances?start_on=MM/DD/YYYY&end_on=MM/DD/YYYY
GET /oportal/api/owner_transactions?start_on=MM/DD/YYYY&end_on=MM/DD/YYYY&limit=100&offset=0
GET /oportal/api/owner_income?start_on=MM/DD/YYYY&end_on=MM/DD/YYYY
GET /oportal/api/owner_expenses?start_on=MM/DD/YYYY&end_on=MM/DD/YYYY
```

## Computing "amount brought in"

- Use `owner_income` or `owner_income_balances` and sum `totalAmount` / `amount`.
- **Include negative income entries** (e.g. NSF reversals) because they reduce
  cash actually brought in.
- Cash out: `owner_expenses` / `owner_expenses_balances`.
- Period net cash flow: `sum(income totalAmount) - sum(expense totalAmount)`.
- If the portal exposes a total directly, prefer it and report the source +
  date range. Otherwise sum with a real calculation and state the assumptions.

## Browser navigation routes (when the script is insufficient)

```text
/oportal/  ->  /oportal/dashboard
/oportal/statements
/oportal/transaction_history
/oportal/documents
/oportal/properties
/oportal/owner_contributions  ->  /oportal/contributions/<id>/new
/oportal/estimate_approvals
```

## NEEDS-VALIDATION

Field names (`totalAmount` vs `amount` vs `total`) and exact response envelope
(bare list vs `{data:[...]}`) should be confirmed on the first real run per
portal. `appfolio_lookup.py::summary` tolerates several shapes but log the raw
JSON on the first call to lock the parser.
