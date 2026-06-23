# AppFolio 2FA and Camofox session persistence

How to log in once and stay logged in, and how 2FA actually behaves.

## Cookies observed in a logged-in owner-portal session

| Cookie | Domain | Expiry | Role |
|---|---|---|---|
| `_oportal_session` | `<company>.appfolio.com` | **session-only**, httpOnly+secure | The auth session. Server expires it after a few hours idle. |
| `af_fingerprint` | `.appfolio.com` | ~400 days | Device/browser fingerprint. Likely the device-recognition signal that lets a re-login skip 2FA. |
| `_sp_id` / `_sp_ses` / `_dd_s` | `.appfolio.com` | mixed | Snowplow + Datadog analytics. Irrelevant to auth. |

**Consequence:** persistence keeps you logged in only as long as the server
session is alive (hours). After that you re-login, but the long-lived
`af_fingerprint` should make that re-login a recognized device (no 2FA), IF
"Remember this device" was used at first login. This is observed-but-unproven;
confirm with a live re-login test (let the session lapse, re-login, see if 2FA
is prompted).

## Camofox session persistence (proven working)

- The Camofox browser server runs a persistence plugin (`plugins/persistence/`)
  that saves Playwright `storageState` (cookies + localStorage) per userId to
  `~/.camofox/profiles/<md5(userId)>/storage-state.json` and restores it on the
  next session for that userId.
- It saves on `session:destroying`, loads on `session:creating`. The store is in
  the home dir and is NOT touched by the `/tmp` Firefox-profile cleanup, so it
  survives a server restart.
- The agent passes a **stable, deterministic userId** per Hermes profile
  (`tools.browser_camofox_state.get_camofox_identity()` -> `hermes_<uuid5>`), so
  the same profile always maps to the same persisted session. That stable userId
  is what `appfolio_lookup.py --user-id` should receive.

## 2FA strategy, best to worst

1. **TOTP shared-secret (best, when the client controls the AppFolio account).**
   Client enables authenticator-app MFA; the setup secret is stored by NoDesk
   (encrypted). The agent generates the 6-digit code itself with `pyotp`. No
   inbox, no SMS, deterministic. Property-manager clients running their own
   AppFolio control this.
2. **Email-2FA auto-read.** If the account has email 2FA enabled, trigger
   "send code via email", then read the freshest AppFolio code email from the
   connected Gmail/Google integration (regex the 6 digits, newer than the send
   time) and enter it. Many PM-managed owner portals do NOT offer email 2FA
   (observed: `user[email_2fa] = false` on Hometown Oklahoma), so this is a
   fallback, not a default.
3. **Human-provided SMS/phone code.** The agent triggers "send code", reports
   "sent to a number ending in ####", and the owner provides the code. Used
   only when 1 and 2 are unavailable.

Always check **"Remember this device"** on first login regardless of method, so
the device cookie persists and 2FA becomes rare instead of per-login.

## Do not

- Store or echo the portal password, full 2FA phone number, or live 2FA codes.
- Trigger repeated SMS codes; each new code can invalidate the prior one.
