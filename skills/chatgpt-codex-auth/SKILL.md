---
name: chatgpt-codex-auth
description: Help a messaging user connect their ChatGPT account for Hermes Codex tasks.
version: 1.0.0
author: NoDesk
---

# ChatGPT / Codex Auth

Use this skill when the Telegram or WhatsApp owner asks to connect, reconnect, authenticate, sign in, or fix ChatGPT/Codex/OpenAI Codex.

## Normal Messaging Flow

1. Check status:

```bash
python3 scripts/codex_auth_device.py status
```

2. If not connected, start the device-code flow:

```bash
python3 scripts/codex_auth_device.py start
```

Send the user the exact `Open:` URL and `Code:` from the command output. Tell them to finish the ChatGPT sign-in page, then message back when done.

3. When the user says they finished sign-in, poll once:

```bash
python3 scripts/codex_auth_device.py poll
```

If it says approval is still pending, ask them to finish the sign-in page and try polling again after they reply. If it says connected, tell them ChatGPT/Codex is connected.

## Important

- Never ask normal clients to paste `auth.json` or token JSON in chat.
- Never print, summarize, or send access tokens or refresh tokens.
- Telegram users must message the bot first. Telegram does not allow bots to start a DM with a user who has not initiated.
- WhatsApp must be paired on the agent first with `hermes whatsapp`.
- If the device code expires, run `python3 scripts/codex_auth_device.py start` again and send the fresh URL/code.
