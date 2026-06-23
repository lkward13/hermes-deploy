---
name: appfolio
description: Log into an AppFolio Owner Portal (browser + 2FA), then pull owner financials (income, expenses, transactions, net cash flow, ownerships) via the portal's authenticated JSON API. Use for property owners on AppFolio when asked about money brought in, statements, transactions, or properties.
version: 0.1.0
author: NoDesk
metadata:
  hermes:
    tags: [AppFolio, owner portal, property management, finance, 2FA, browser]
---

# AppFolio Owner Portal

AppFolio has **no public API** (it is partner-gated), so this integration works
by browser. The agent logs into the company owner portal with the Camofox
browser, then reuses that same authenticated session to call the portal's
internal JSON endpoints under `/oportal/api/`. `appfolio_lookup.py` is the
deterministic data layer; the browser handles only login + 2FA.

> Status: v0.1. The login flow is proven; `appfolio_lookup.py` endpoint shapes
> are from observed live sessions and should be confirmed on the first real run
> per portal.

## When to use

A property owner on AppFolio asks something like "how much did I bring in this
month", "show my statements / transactions", "what properties do I own", or
"net cash flow last quarter."

## The flow (always in this order)

1. **Log in (browser).** Navigate to `https://<company>.appfolio.com/oportal/users/log_in`,
   enter the owner's email + password, submit.
2. **2FA.** If AppFolio shows "device not recognized":
   - **Check "Remember this device"** so AppFolio issues its long-lived device
     cookie (Camofox persists it, so future logins skip 2FA until it expires).
   - Trigger the code by the available method (SMS/phone, or email if the
     account enabled email 2FA). For email-2FA accounts, the agent can read the
     code from the connected Gmail/Google integration; otherwise ask the owner
     for the code shown "sent to a number ending in ####." Use the code
     immediately in the **same browser session**.
   - Best autonomous path (when the owner controls the account): authenticator
     app (TOTP) with the secret stored by NoDesk, so the agent generates the
     code itself. See `references/2fa-and-persistence.md`.
3. **Pull data (script).** Once logged in, Camofox has persisted the session
   cookies. Call `appfolio_lookup.py` with the agent's Camofox `--user-id` (so
   it reads those cookies) instead of scraping the React pages.

## Data layer: appfolio_lookup.py

```bash
# The agent's Camofox userId comes from tools.browser_camofox_state.get_camofox_identity()
UID=hermes_xxxxxxxxxx

python appfolio_lookup.py whoami        --user-id $UID
python appfolio_lookup.py ownerships    --user-id $UID
python appfolio_lookup.py income        --user-id $UID --start 06/01/2026 --end 06/30/2026
python appfolio_lookup.py expenses      --user-id $UID --start 06/01/2026 --end 06/30/2026
python appfolio_lookup.py transactions  --user-id $UID --start 06/01/2026 --end 06/30/2026 --limit 100
python appfolio_lookup.py summary       --user-id $UID --start 06/01/2026 --end 06/30/2026
```

- All output is JSON on stdout. Dates are **MM/DD/YYYY** (AppFolio's format).
- `summary` returns `{gross_income, gross_expenses, net_cash_flow}` and counts.
  It sums income (including negative entries like NSF reversals, which reduce
  cash in) minus expenses.
- The company subdomain is inferred from the session cookies; pass `--company`
  to override.

## Auth-expired handling

The owner-portal auth cookie (`_oportal_session`) is session-only and AppFolio
expires it after a few hours. If a `appfolio_lookup.py` call returns
`{"ok": false, "code": "auth_expired"}`, the session lapsed: re-run the browser
login (step 1-2), then retry the script. The persisted device cookie usually
lets that re-login skip 2FA.

## Pitfalls

- Do **not** mix a browser login with a separate `requests` login. Log in via
  the browser; this script only *replays* the resulting cookies.
- 2FA codes are one-time and session-tied. Requesting a new code can invalidate
  the previous one. Use the latest immediately.
- Never store or echo the portal password or full 2FA phone number.
- Owner portal (`/oportal/`) only. Property-manager staff accounts use the full
  AppFolio app at a different surface and stricter MFA; not covered here yet.

## References

- `references/oportal-api.md`: observed `/oportal/api/` endpoints + field names.
- `references/2fa-and-persistence.md`: 2FA methods, device-trust cookie, and
  Camofox session persistence (the `~/.camofox/profiles/<id>/storage-state.json`
  store keyed on the agent's stable userId).
