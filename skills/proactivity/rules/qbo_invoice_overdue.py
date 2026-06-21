"""Proactivity rule: qbo.invoice_overdue.

Catch open QuickBooks invoices that are past their DueDate so the owner can
collect today. One Signal per overdue invoice, ranked by Balance, with a
one-tap "send a pay link" action.

Read-only by contract: the only side effect is shelling qbo-invoicing's
read-only lookup script. The whole body is wrapped in try/except and returns
[] on any error (the engine isolates failures, but we stay safe anyway).

House rule: zero em dashes anywhere. Use periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="qbo.invoice_overdue",
    title="Overdue invoice",
    providers=("qbo",),
    category="collect_now",
    cadence_minutes=60,
    cooldown_hours=72.0,
    materiality={"min_amount": 250.0},
)


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s):
    """QBO dates are 'YYYY-MM-DD'. Return a date or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _money(v: float) -> str:
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


def _days_word(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def evaluate(ctx) -> list:
    try:
        records = ctx.run_skill(
            "qbo-invoicing",
            "qbo_lookup.py",
            ["list", "Invoice", "--where", "Balance > '0'", "--json"],
        )
        if not isinstance(records, list):
            return []

        today = ctx.now.date()
        signals = []

        for r in records:
            if not isinstance(r, dict):
                continue

            balance = _to_float(r.get("Balance"))
            if balance <= 0:
                continue

            inv_id = str(r.get("Id") or "").strip()
            if not inv_id:
                continue

            due = _parse_date(r.get("DueDate"))
            if due is None:
                continue

            days_late = (today - due).days
            if days_late <= 0:
                continue

            who = (r.get("CustomerRef") or {}).get("name") or "A customer"
            doc = str(r.get("DocNumber") or "").strip()
            doc_tag = f" (invoice #{doc})" if doc else ""

            summary = (
                f"{who} owes {_money(balance)}{doc_tag}, "
                f"{_days_word(days_late)} past due."
            )
            urgency = "high" if days_late >= 30 else "normal"

            signals.append(
                Signal(
                    entity_id=f"invoice:{inv_id}",
                    summary=summary,
                    proposal="Text them a pay link to collect now?",
                    action=Action(
                        kind="qbo.send_payment_link",
                        params={"invoice_id": inv_id},
                    ),
                    amount=balance,
                    count=1,
                    urgency=urgency,
                )
            )

        return signals
    except Exception:
        return []
