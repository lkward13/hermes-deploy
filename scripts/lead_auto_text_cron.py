#!/usr/bin/env python3
"""Cron entrypoint for lead-auto-text skill.

Runs every 60s via Hermes cron. Checks for new Facebook leads only.
Inbound SMS replies are handled by the ClickSend webhook subscription
so the subagent can react immediately instead of polling.

Outputs a prompt telling the main agent to DELEGATE to the lead subagent.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

SKILL_DIR = os.path.join(os.path.expanduser("~"), ".hermes", "skills", "lead-auto-text")
PYTHON = sys.executable
LEADS_FILE = os.path.join(SKILL_DIR, "leads.json")

BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "the business")
OWNER_NAME = os.environ.get("OWNER_NAME", "the owner")
OWNER_PHONE = os.environ.get("OWNER_PHONE", "")
ADMIN_NAME = os.environ.get("ADMIN_NAME", "admin")
ADMIN_PHONE = os.environ.get("ADMIN_PHONE", "")
SUBAGENT_NAME = os.environ.get("AGENT_SUBAGENT_NAME", "Richard")


def run_script(script_name: str, args: list = None) -> str:
    cmd = [PYTHON, os.path.join(SKILL_DIR, script_name)] + (args or [])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        return json.dumps({"error": str(e)})


def load_leads() -> dict:
    if not os.path.exists(LEADS_FILE):
        return {"leads": {}}
    with open(LEADS_FILE, "r") as f:
        return json.load(f)


def check_new_leads() -> list:
    output = run_script("poll_leads.py")
    try:
        data = json.loads(output)
        return data.get("new_leads", [])
    except json.JSONDecodeError:
        return []


def check_business_hours() -> bool:
    utc_now = datetime.now(timezone.utc)
    central_offset = timedelta(hours=-5)
    central_now = utc_now + central_offset
    return 8 <= central_now.hour < 20


def build_subagent_context(new_leads, leads_data) -> str:
    parts = []
    parts.append(
        f"You are {SUBAGENT_NAME}, the lead engagement specialist for {BUSINESS_NAME}. "
        f"You're a friendly, down-to-earth professional. You're customer service and scheduling "
        f"- NOT a salesperson. No pressure, no corporate speak. Text like a real person. "
        f"Always introduce yourself as '{SUBAGENT_NAME} with {BUSINESS_NAME}'. "
        f"CRITICAL: NEVER discuss pricing, costs, estimates, ranges, or ballparks. "
        f"If a lead asks about price, politely explain every project is different and you don't "
        f"want to misquote them - {OWNER_NAME} needs to see it in person. Pivot to scheduling. "
        f"NEVER mention {ADMIN_NAME} to leads - only reference {OWNER_NAME} by name. "
        f"NEVER use em dashes in texts."
    )
    parts.append(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    parts.append("")

    if new_leads:
        parts.append(f"NEW LEADS ({len(new_leads)}):")
        for lead in new_leads:
            parts.append(f"  Name: {lead['name']}")
            parts.append(f"  Phone: {lead['phone']}")
            parts.append(f"  Email: {lead.get('email', 'n/a')}")
            if lead.get("form_data"):
                for k, v in lead["form_data"].items():
                    if k not in ("first_name", "last_name", "full_name", "phone_number", "phone", "email"):
                        parts.append(f"  {k}: {v}")
            parts.append("")
        parts.append(
            "ACTION: Text each new lead immediately. Use send_sms.py. "
            f"Identify as {BUSINESS_NAME}. Use their first name. "
            "Ask a qualifying question. Then register them with lead_state.py."
        )
        parts.append("")

    parts.append(f"Scripts are at {SKILL_DIR}/")
    parts.append(f"Use Python at: {PYTHON}")
    parts.append(f"Read SKILL.md at {SKILL_DIR}/SKILL.md for conversation guidelines.")

    return "\n".join(parts)


def main():
    if not check_business_hours():
        return 0

    new_leads = check_new_leads()
    leads_data = load_leads()

    if not new_leads:
        return 0

    subagent_context = build_subagent_context(new_leads, leads_data)

    prompt_parts = []
    prompt_parts.append("[LEAD AUTO-TEXT — DELEGATE TO SUBAGENT]")
    prompt_parts.append("")

    if new_leads:
        names = ", ".join(l["name"] for l in new_leads)
        prompt_parts.append(f"New lead(s): {names}")

    prompt_parts.append("")
    prompt_parts.append("IMMEDIATELY delegate this to a subagent using delegate_task:")
    prompt_parts.append("")
    prompt_parts.append("delegate_task(")
    prompt_parts.append(f'    goal="Handle lead auto-text for {BUSINESS_NAME}",')
    prompt_parts.append(f'    context="""{subagent_context}""",')
    prompt_parts.append('    toolsets=["terminal", "file"]')
    prompt_parts.append(")")
    prompt_parts.append("")
    prompt_parts.append(
        f"After delegating, send {ADMIN_NAME} a brief Telegram update about what's happening. "
        "Do NOT handle the lead conversation yourself."
    )

    print("\n".join(prompt_parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
