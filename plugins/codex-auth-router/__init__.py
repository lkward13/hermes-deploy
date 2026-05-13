"""Pre-route ChatGPT/Codex auth messages before Hermes model dispatch."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


START_PATTERNS = (
    re.compile(r"^\s*(connect|auth|authenticate|sign\s*in|login|log\s*in)\s+(chatgpt|codex|openai(?:\s+codex)?)\s*[.!?]*\s*$", re.I),
    re.compile(r"^\s*(chatgpt|codex|openai(?:\s+codex)?)\s+(connect|auth|authenticate|sign\s*in|login|log\s*in)\s*[.!?]*\s*$", re.I),
    re.compile(r"^\s*(reconnect|reauth|reauthenticate)\s+(chatgpt|codex|openai(?:\s+codex)?)\s*[.!?]*\s*$", re.I),
)

SPECIFIC_DONE_PATTERNS = (
    re.compile(r"^\s*i\s+(am\s+)?(finished|done|complete|completed)\s+(with\s+)?(chatgpt|codex|openai(?:\s+codex)?)\s*(sign[\s-]?in|auth|login)?\s*[.!?]*\s*$", re.I),
    re.compile(r"^\s*(i\s+)?(finished|completed|approved)\s+(the\s+)?(chatgpt|codex|openai(?:\s+codex)?)\s*(sign[\s-]?in|auth|login|approval)?\s*[.!?]*\s*$", re.I),
)

GENERIC_DONE_PATTERNS = (
    re.compile(r"^\s*(done|finished|complete|completed|approved)\s*[.!?]*\s*$", re.I),
)

STATUS_PATTERNS = (
    re.compile(r"^\s*(chatgpt|codex|openai(?:\s+codex)?)\s+(status|connected\??)\s*$", re.I),
    re.compile(r"^\s*(status|is\s+connected)\s+(chatgpt|codex|openai(?:\s+codex)?)\s*\??\s*$", re.I),
)


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", handle_codex_auth_message)


def handle_codex_auth_message(event, gateway, **_kwargs):
    text = (getattr(event, "text", None) or "").strip()
    action = _classify(text)
    if action is None:
        return None

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reply_for_action(action, event, gateway))
    except RuntimeError:
        return None

    return {"action": "skip", "reason": f"codex-auth-{action}"}


def _classify(text: str) -> str | None:
    if not text:
        return None
    if any(pattern.match(text) for pattern in START_PATTERNS):
        return "start"
    if any(pattern.match(text) for pattern in STATUS_PATTERNS):
        return "status"
    if any(pattern.match(text) for pattern in SPECIFIC_DONE_PATTERNS):
        return "poll"
    if any(pattern.match(text) for pattern in GENERIC_DONE_PATTERNS) and _pending_auth_exists():
        return "poll"
    return None


async def _reply_for_action(action: str, event, gateway) -> None:
    source = getattr(event, "source", None)
    adapter = getattr(gateway, "adapters", {}).get(getattr(source, "platform", None))
    if adapter is None or source is None:
        return

    processing = {
        "start": "Starting ChatGPT sign-in...",
        "status": "Checking ChatGPT connection...",
        "poll": "Checking whether ChatGPT approved the sign-in...",
    }[action]
    await _send(adapter, source, processing, event=event)

    try:
        message = await asyncio.to_thread(_message_for_action, action)
    except Exception as exc:
        message = (
            "I hit an error while checking ChatGPT/Codex auth. "
            f"Ask support to check Hermes logs for `{exc.__class__.__name__}`."
        )

    await _send(adapter, source, message, event=event)


def _message_for_action(action: str) -> str:
    if action == "status":
        status = _run_helper("status")
        return _status_message(status.returncode, status.stdout)

    if action == "poll":
        poll = _run_helper("poll")
        return _poll_message(poll.returncode, poll.stdout)

    status = _run_helper("status")
    if status.returncode == 0:
        return "ChatGPT/Codex is already connected. You can ask me to work now."
    start = _run_helper("start")
    return _start_message(start.returncode, start.stdout)


def _run_helper(command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    hermes_home = _hermes_home()
    env["HERMES_HOME"] = str(hermes_home)
    helper = hermes_home / "scripts" / "codex_auth_device.py"
    return subprocess.run(
        [sys.executable, str(helper), command],
        cwd=hermes_home,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()


def _pending_auth_exists() -> bool:
    return (_hermes_home() / "credentials" / "codex_auth_pending.json").exists()


def _start_message(returncode: int, output: str) -> str:
    if returncode != 0:
        return _failure_message("starting ChatGPT sign-in", output)

    url = _extract_line_value(output, "Open")
    code = _extract_line_value(output, "Code")
    if not url or not code:
        return _failure_message("starting ChatGPT sign-in", output)

    return (
        "ChatGPT sign-in is ready.\n\n"
        f"Open: {url}\n"
        f"Code: `{code}`\n\n"
        "Finish the approval page, then message me: `I finished ChatGPT sign-in`"
    )


def _poll_message(returncode: int, output: str) -> str:
    if returncode == 0:
        return "ChatGPT/Codex is connected. You can ask me to work now."
    if returncode == 1:
        return "Still waiting on ChatGPT approval. Finish the sign-in page, then message me again: `I finished ChatGPT sign-in`"
    if returncode in {2, 3}:
        return "There is no active ChatGPT sign-in code, or it expired. Message me `connect ChatGPT` to get a fresh link and code."
    return _failure_message("checking ChatGPT approval", output)


def _status_message(returncode: int, output: str) -> str:
    if returncode == 0:
        return "ChatGPT/Codex is connected."
    if returncode == 1:
        return "ChatGPT/Codex sign-in is pending. Finish the approval page, then message me: `I finished ChatGPT sign-in`"
    if returncode == 2:
        return "ChatGPT/Codex is not connected yet. Message me `connect ChatGPT` to start."
    return _failure_message("checking ChatGPT status", output)


def _failure_message(action: str, output: str) -> str:
    detail = _safe_output_tail(output)
    if detail:
        return f"I could not finish {action}: {detail}"
    return f"I could not finish {action}. Ask support to check Hermes logs."


def _extract_line_value(output: str, label: str) -> str:
    prefix = f"{label}:"
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _safe_output_tail(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    tail = lines[-1]
    if len(tail) > 240:
        tail = tail[:237] + "..."
    return tail


async def _send(adapter: Any, source: Any, content: str, *, event: Any) -> None:
    metadata = _thread_metadata(source, event)
    await adapter.send(str(source.chat_id), content, metadata=metadata)


def _thread_metadata(source: Any, event: Any) -> dict[str, str] | None:
    thread_id = getattr(source, "thread_id", None)
    if thread_id is None:
        return None

    metadata = {"thread_id": str(thread_id)}
    platform = getattr(getattr(source, "platform", None), "value", getattr(source, "platform", ""))
    if str(platform).lower() == "telegram" and getattr(source, "chat_type", None) == "dm":
        message_id = getattr(event, "message_id", None)
        if message_id is not None:
            metadata["telegram_reply_to_message_id"] = str(message_id)
            metadata["telegram_dm_topic_reply_fallback"] = True
    return metadata
