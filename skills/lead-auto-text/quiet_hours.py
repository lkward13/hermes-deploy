#!/usr/bin/env python3
"""Quiet-hours guard for LEAD-facing texts (a hard-coded lever, runs before the LLM).

Texting a lead at 2am is illegal in spirit (TCPA quiet hours are 8pm-8am local
to the *recipient*) and torches trust. This computes whether it's an OK time to
text in the tenant's own timezone (HERMES_TIMEZONE), so the engine can defer a
first-touch or follow-up to the morning instead of firing at night.

Window: texting allowed between LEAD_TEXT_START_HOUR (default 8) and
LEAD_TEXT_END_HOUR (default 21), local time. Outside that = quiet.

NOTE: this applies to LEAD-facing messages only. Owner/admin notifications
(approval requests, alerts) are exempt and must NOT be gated on quiet hours.

Usage:
  python3 quiet_hours.py            -> prints {"ok": true/false, ...}, exit 0
Importable:
  from quiet_hours import text_ok_now; ok, info = text_ok_now()
"""
import json
import os
import sys
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 fallback
    ZoneInfo = None

TZ_NAME = os.environ.get("HERMES_TIMEZONE", "").strip()
START_HOUR = int(os.environ.get("LEAD_TEXT_START_HOUR", "8"))
END_HOUR = int(os.environ.get("LEAD_TEXT_END_HOUR", "21"))


def _now_local() -> datetime:
    if TZ_NAME and ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(TZ_NAME))
        except Exception:
            pass
    # Fall back to the VPS local clock (UTC). Better to be conservative than to
    # crash; the agent still gets a definite answer.
    return datetime.now()


def text_ok_now() -> tuple[bool, dict]:
    now = _now_local()
    ok = START_HOUR <= now.hour < END_HOUR
    info = {
        "ok": ok,
        "now_local": now.isoformat(),
        "tz": TZ_NAME or "server-local(UTC)",
        "window": f"{START_HOUR:02d}:00-{END_HOUR:02d}:00 local",
    }
    if not ok:
        nxt = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
        if now.hour >= END_HOUR:
            nxt = nxt + timedelta(days=1)
        info["next_ok_local"] = nxt.isoformat()
    return ok, info


def main() -> int:
    _, info = text_ok_now()
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
