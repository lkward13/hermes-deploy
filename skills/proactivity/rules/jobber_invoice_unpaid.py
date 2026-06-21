"""Proactivity rule: jobber.invoice_unpaid (collect now).

Detects Jobber invoices the customer has sent out that still carry an open
balance, so the owner can fire off a one-tap payment reminder instead of letting
the money sit. Read-only: it only runs the jobber lookup skill in --json mode and
shapes the result into Signals. Defensive by contract: the whole body is wrapped
in try/except and returns [] on any error (the engine isolates rule failures, but
we never want a noisy integration to sink a tick).

Data source: skills/jobber/jobber_lookup.py invoices --json, which prints a JSON
array of invoice node dicts of the shape:
  {
    "id": "Z2lk...",
    "invoiceNumber": "1042",
    "subject": "Spring cleanup",
    "invoiceStatus": "AWAITING_PAYMENT",   # DRAFT|AWAITING_PAYMENT|PAID|PAST_DUE|BAD_DEBT|...
    "total": 1900.0,
    "invoiceBalance": 1900.0,              # what is still owed
    "issuedDate": "2026-05-20",
    "dueDate": "2026-06-04",
    "client": {"id": "...", "name": {"full": "Coastal Builders"}}
  }

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere in owner copy.
Use periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="jobber.invoice_unpaid",
    title="Unpaid Jobber invoice",
    providers=("jobber",),
    category="collect_now",
    cadence_minutes=120,
    default_autonomy="draft",
    cooldown_hours=72.0,
    materiality={"min_amount": 250.0},
)


# Invoice statuses that mean "this is paid or not yet a real bill" and so should
# never trigger a collect-now ping, regardless of any stale balance field.
_NOT_OWED = {"PAID", "DRAFT", "VOID", "VOIDED", "BAD_DEBT", "WRITE_OFF", "WRITTEN_OFF"}


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _days_late(due_date: str, now: datetime.datetime) -> int:
    """Whole days past dueDate (YYYY-MM-DD). 0 if missing or not yet due."""
    if not due_date:
        return 0
    try:
        due = datetime.date.fromisoformat(str(due_date)[:10])
    except (TypeError, ValueError):
        return 0
    delta = (now.date() - due).days
    return delta if delta > 0 else 0


def _money(v: float) -> str:
    """$1,900 with no trailing cents when whole, else $1,900.50."""
    if v == int(v):
        return "${:,.0f}".format(v)
    return "${:,.2f}".format(v)


def evaluate(ctx) -> list:
    try:
        rows = ctx.run_skill("jobber", "jobber_lookup.py", ["invoices", "--json"])
        if not isinstance(rows, list):
            return []

        signals = []
        now = ctx.now if isinstance(ctx.now, datetime.datetime) else datetime.datetime.now(datetime.timezone.utc)

        for inv in rows:
            if not isinstance(inv, dict):
                continue

            inv_id = inv.get("id")
            if not inv_id:
                continue

            status = str(inv.get("invoiceStatus") or "").upper()
            if status in _NOT_OWED:
                continue

            balance = _to_float(inv.get("invoiceBalance"))
            if balance <= 0:
                continue  # nothing actually owed

            # Identify the customer in plain words, no "several".
            client = inv.get("client") or {}
            name_obj = client.get("name") if isinstance(client, dict) else None
            who = ""
            if isinstance(name_obj, dict):
                who = (name_obj.get("full") or "").strip()
            if not who:
                who = "A client"

            number = str(inv.get("invoiceNumber") or "").strip()
            inv_label = "invoice #" + number if number else "an invoice"

            late = _days_late(inv.get("dueDate"), now)
            if late > 0:
                tail = "{} days past due.".format(late)
                urgency = "high" if late >= 14 else "normal"
            else:
                tail = "still unpaid."
                urgency = "normal"

            summary = "{} owes {} on {}, {}".format(who, _money(balance), inv_label, tail)
            proposal = "Send a payment reminder?"

            signals.append(
                Signal(
                    entity_id="invoice:{}".format(inv_id),
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="jobber.send_reminder",
                        params={
                            "invoice_id": inv_id,
                            "invoice_number": number,
                            "client_name": who,
                            "balance": balance,
                        },
                    ),
                    amount=balance,
                    count=1,
                    urgency=urgency,
                )
            )

        return signals
    except Exception:
        return []
