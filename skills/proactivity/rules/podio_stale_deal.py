"""Rule: podio.stale_deal (hot_leads).

A lead sitting in the customer's Podio pipeline that has not moved in weeks is a
deal quietly dying. Podio is the CRM where new jobs land ("New Lead") and get
quoted ("Quoted"); once an invoice goes out the item flips to "Invoice Sent" /
"Invoice Paid", and dead ones go to "Cancelled". So an item still parked in
New Lead or Quoted, with an old date and a real dollar value attached, is money
the owner already half-earned and is about to let walk. This rule surfaces those
so the owner can shoot one follow-up before the lead goes cold for good.

The Podio skill auto-discovers the customer's leads/jobs app and lists items via
``podio_lookup.py --list-recent --limit N --json``, returning one dict per item
(item_id, name, phone, job_description, date, invoice_status, link). Podio has no
dedicated "deal value" field on this app, so we read the dollar amount out of the
job_description free text (e.g. "Reroof, $6,500"). No amount, no ping: a lead we
cannot price is not worth a money-at-risk nudge.

Read-only, cheap, defensive: the whole body is wrapped and any error returns [].

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use
periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime
import re

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

RULE = RuleSpec(
    key="podio.stale_deal",
    title="Stale lead with a dollar value",
    providers=("podio",),
    category="hot_leads",
    cadence_minutes=720,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={},
)

# How many recent items to pull and scan each tick.
_LIST_LIMIT = 100

# Statuses that mean "still open, still winnable" on the Podio leads/jobs app.
# Anything else (Invoice Sent, Invoice Paid, Cancelled) is closed or in motion
# and not a stale-deal nudge. An empty/unset status is treated as still open.
_OPEN_STATUSES = {"new lead", "quoted", ""}

# A lead is "stale" once it has gone quiet for this long. Under this it is still
# fresh and a nudge would be noise. Capped so we do not nag about ancient dead
# leads forever: past the upper bound the deal is effectively gone, not stale.
_STALE_LOWER_DAYS = 14
_STALE_UPPER_DAYS = 120

# Only nudge on deals worth chasing. The rule owns this floor because the spec
# sets engine materiality to {} (the dollar value is parsed here, not a field).
_MIN_VALUE = 500.0

# Match a dollar figure in free text: "$6,500", "$6500", "$6,500.00", "$2k".
_MONEY_RE = re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(k\b)?", re.IGNORECASE)


def _parse_date(raw):
    """Parse a Podio date (the skill emits 'YYYY-MM-DD') to an aware UTC
    datetime at midnight, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip().split(" ")[0].split("T")[0]
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return d.replace(tzinfo=datetime.timezone.utc)


def _parse_value(text) -> float:
    """Pull the largest dollar figure out of free text. 0.0 if none found.
    Handles thousands commas and a trailing 'k' shorthand ($2k => 2000)."""
    if not isinstance(text, str) or "$" not in text:
        return 0.0
    best = 0.0
    for m in _MONEY_RE.finditer(text):
        digits = m.group(1).replace(",", "")
        try:
            val = float(digits)
        except ValueError:
            continue
        if m.group(2):  # trailing "k"
            val *= 1000.0
        if val > best:
            best = val
    return best


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


def _name(item) -> str:
    name = (item.get("name") or item.get("title") or "").strip()
    return name or "A lead"


def evaluate(ctx) -> list:
    try:
        rows = ctx.run_skill(
            "podio",
            "podio_lookup.py",
            ["--list-recent", "--limit", str(_LIST_LIMIT), "--json"],
        )
        if not isinstance(rows, list):
            return []

        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        signals = []
        for item in rows:
            if not isinstance(item, dict):
                continue

            status = str(item.get("invoice_status") or "").strip().lower()
            if status not in _OPEN_STATUSES:
                continue

            item_id = item.get("item_id")
            if not item_id:
                continue

            last = _parse_date(item.get("date"))
            if last is None:
                continue
            age_days = (now - last).total_seconds() / 86400.0
            if age_days < _STALE_LOWER_DAYS or age_days > _STALE_UPPER_DAYS:
                continue

            job = item.get("job_description") or ""
            amount = _parse_value(job)
            if amount < _MIN_VALUE:
                continue

            name = _name(item)
            days = int(round(age_days))
            stage = "Quoted" if status == "quoted" else "New Lead"
            job_short = job.strip()
            if len(job_short) > 60:
                job_short = job_short[:57].rstrip() + "..."
            job_part = f" ({job_short})" if job_short else ""

            summary = (
                f"{name}{job_part} is a {_money(amount)} deal stuck on \"{stage}\" "
                f"in Podio, no movement in {days} days. It is going cold."
            )
            proposal = "Want me to send them a quick follow-up to revive it?"

            signals.append(
                Signal(
                    entity_id=f"podio-deal:{item_id}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="podio.nudge_deal",
                        params={
                            "item_id": str(item_id),
                            "name": name,
                            "phone": (item.get("phone") or "").strip(),
                            "email": (item.get("email") or "").strip(),
                            "status": stage,
                            "amount": amount,
                            "days_stale": days,
                            "link": (item.get("link") or "").strip(),
                        },
                    ),
                    amount=amount,
                    count=1,
                    urgency="high" if age_days >= 45 else "normal",
                )
            )

        return signals
    except Exception:
        return []
