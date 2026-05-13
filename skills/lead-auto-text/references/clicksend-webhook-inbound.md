# ClickSend inbound webhook notes

Session takeaway: inbound SMS replies for `lead-auto-text` should be handled by the ClickSend webhook route, not by cron polling.

## What changed
- Cron no longer polls `check_sms.py --since 2` for replies.
- Cron is now limited to discovering new Facebook leads.
- Inbound replies are expected to arrive on the local webhook route: `http://localhost:8644/webhooks/clicksend-sms`.

## Operational notes
- The webhook subscription is named `clicksend-sms` and delivers to Telegram.
- Earlier logs showed `401 Invalid signature` on this route before later successful delivery, so signature/auth setup should be verified whenever replies stop arriving.
- If Richard is not responding, check the webhook path and signature handling before falling back to any polling logic.

## Verification hints
- Look for successful `POST /webhooks/clicksend-sms` responses.
- Confirm the webhook route produces a delegated Richard task and acquires/releases the lead lock.
- Avoid reintroducing narrow reply polling unless webhook delivery is unavailable.