"""Handle the customer's first `/start <token>` Telegram message.

When a new NoDesk customer completes onboarding on the connect page and taps
"Open Telegram & tap Start", they're sent to `t.me/<bot>?start=<token>`
which delivers a `/start <token>` message to this bot. Telegram opens a
brand-new chat between bot and user, which solves the chicken-and-egg that
prevented `_send_welcome_telegram` (NoDesk side) from ever reaching the user.

This plugin intercepts that `/start <token>` event BEFORE the gateway
dispatches it to the LLM, calls NoDesk's `/api/agent/{client_id}/telegram-bound`
endpoint to bind the chat_id, then sends a friendly welcome reply in the
same chat. The LLM never sees the /start.

Auth pattern matches the rest of NoDesk's agent callbacks: pass the agent's
own `HERMES_CLIENT_ID` as the `X-Hermes-Token` header. The endpoint checks
that the start_token in the body matches a magic_link row scoped to this
client, so a leaked /start token only works for that one customer's bot.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

# `/start TOKEN` — token is base64url-safe; allow letters, digits, _, -
START_PATTERN = re.compile(r"^\s*/start\s+([A-Za-z0-9_-]{16,})\s*$")

WELCOME_MESSAGE = (
    "Great news: your assistant is live. Bad news for your to-do list — same reason. 🎉\n\n"
    "Zero sick days. Zero coffee breaks. Zero passive-aggressive 'per my last message' emails.\n\n"
    "I'm ready when you are. What do we need done today? 💼"
)


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", handle_start_message)


def handle_start_message(event, gateway, **_kwargs):
    text = (getattr(event, "text", None) or "").strip()
    logger.info("nodesk-start-binder: pre_gateway_dispatch invoked, text=%r", text[:80])
    match = START_PATTERN.match(text)
    if not match:
        logger.info("nodesk-start-binder: text does not match /start <token> pattern")
        return None

    token = match.group(1)
    source = getattr(event, "source", None)
    if source is None:
        return None

    platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", ""))
    if str(platform).lower() != "telegram":
        # /start on Slack etc. — not our concern
        return None

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bind_and_welcome(token, event, gateway))
    except RuntimeError:
        return None

    # Don't dispatch the /start to the LLM — we've handled it.
    return {"action": "skip", "reason": "nodesk-start-binder"}


async def _bind_and_welcome(token: str, event, gateway) -> None:
    source = event.source
    chat_id = str(getattr(source, "chat_id", "") or "")
    user_id = getattr(source, "user_id", None) or getattr(source, "sender_id", None)
    username = getattr(source, "username", "") or ""
    first_name = getattr(source, "first_name", "") or getattr(source, "sender_name", "") or ""

    client_id = os.environ.get("HERMES_CLIENT_ID", "").strip()
    nodesk_url = os.environ.get("NODESK_BASE_URL", "").strip().rstrip("/")
    if not client_id or not nodesk_url:
        logger.warning("nodesk-start-binder: HERMES_CLIENT_ID or NODESK_BASE_URL not set; skipping bind")
        return

    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "start_token": token,
    }

    try:
        resp = await asyncio.to_thread(
            requests.post,
            f"{nodesk_url}/api/agent/{client_id}/telegram-bound",
            json=payload,
            headers={"X-Hermes-Token": client_id, "Content-Type": "application/json"},
            timeout=15,
        )
    except Exception:
        logger.exception("nodesk-start-binder: bind call failed; not sending welcome")
        return

    if resp.status_code == 403:
        logger.warning("nodesk-start-binder: bind rejected (403) — start token did not match this client")
        return
    if resp.status_code == 409:
        # Different chat_id already bound. Log but stay quiet to the user.
        logger.warning("nodesk-start-binder: bind conflict (409) — different chat already bound")
        return
    if resp.status_code >= 400:
        logger.warning("nodesk-start-binder: bind failed (%s): %s", resp.status_code, resp.text[:200])
        return

    # Bind succeeded — send the welcome in this same chat. Chat now exists
    # at the Telegram protocol level (user just sent /start), so this will
    # actually go through.
    adapter = gateway.adapters.get(getattr(source, "platform", None))
    if adapter is None:
        logger.warning("nodesk-start-binder: no adapter for platform %s", platform)
        return

    try:
        await adapter.send(chat_id, WELCOME_MESSAGE)
        logger.info("nodesk-start-binder: bound chat_id=%s and sent welcome", chat_id)
    except Exception:
        logger.exception("nodesk-start-binder: welcome send failed")
