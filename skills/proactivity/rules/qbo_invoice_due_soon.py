"""Rule: qbo.invoice_due_soon.

A large open invoice within 3 days of its DueDate (and not yet past due). The
heads-up before money slips into overdue, so the owner can nudge the customer
while the invoice is still "due" and not "late". Pairs with qbo.invoice_overdue
(past due) and qbo.invoice_aging (30/60/90), which cover the after-the-fact side.

Read-only: pulls open invoices via the qbo-invoicing skill's read-only lookup
(qbo_lookup.py list Invoice --json) and filters in-process. Never writes, never
refreshes a token, never raises (the engine isolates failures, but be safe too).

House rule: zero em dashes anywhere. Periods, commas, colons, parens only.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

# How close to the due date counts as "due soon" (inclusive, in days).
_DUE_WINDOW_DAYS = 3

RULE = RuleSpec(
    key="qbo.invoice_due_soon",
    title="Invoice due soon",
    providers=("qbo",),
    category="collect_now",
    cadence_minutes=720,                  # twice a day is plenty for a 3-day window
    default_autonomy="draft",
    cooldown_hours=168.0,                 # one heads-up per invoice per week
    materiality={"min_amount": 500.0},    # only the invoices big enough to chase early
)


def _parse_date(raw):
    """Parse a QBO 'YYYY-MM-DD' date string into a date, or None."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except (ValueError, TypeError):
        return None


def _money(v):
    """Best-effort float of a QBO amount/balance, or None."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt_amount(v):
    """'$1,900' for whole dollars, '$1,234.56' otherwise. No trailing .00."""
    try:
        if float(v).is_integer():
            return "${:,.0f}".format(float(v))
        return "${:,.2f}".format(float(v))
    except (TypeError, ValueError):
        return "$" + str(v)


def _days_phrase(days):
    """Plain, specific countdown copy: today, tomorrow, or in N days."""
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return "in {} days".format(days)


def evaluate(ctx) -> list:
    try:
        today = ctx.now.date()

        # Read-only pull of all open invoices (Balance > 0). We filter the due
        # window in-process so a quirky QBO date comparison can never hide a hit.
        records = ctx.run_skill(
            "qbo-invoicing",
            "qbo_lookup.py",
            ["--json", "list", "Invoice", "--where", "Balance > '0'", "--limit", "200"],
        )
        if not isinstance(records, list):
            return []

        signals = []
        for r in records:
            if not isinstance(r, dict):
                continue

            inv_id = str(r.get("Id") or "").strip()
            if not inv_id:
                continue

            due = _parse_date(r.get("DueDate"))
            if due is None:
                continue

            days_out = (due - today).days
            # Only the heads-up window: due within the next 3 days, not yet past
            # due (overdue invoices belong to qbo.invoice_overdue, not here).
            if days_out < 0 or days_out > _DUE_WINDOW_DAYS:
                continue

            balance = _money(r.get("Balance"))
            if balance is None or balance <= 0:
                continue

            who = ((r.get("CustomerRef") or {}).get("name") or "A customer").strip()
            doc = str(r.get("DocNumber") or "").strip()
            doc_phrase = " (invoice #{})".format(doc) if doc else ""
            when = _days_phrase(days_out)

            summary = "{who} owes {amt}{doc}, due {when}.".format(
                who=who, amt=_fmt_amount(balance), doc=doc_phrase, when=when,
            )

            signals.append(
                Signal(
                    entity_id="invoice:{}".format(inv_id),
                    amount=balance,
                    summary=summary,
                    proposal="Want me to send them a reminder before it is due?",
                    action=Action(
                        kind="qbo.send_reminder",
                        params={"invoice_id": inv_id},
                    ),
                    urgency="high" if days_out <= 1 else "normal",
                )
            )

        return signals
    except Exception:
        return []
