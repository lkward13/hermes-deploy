"""Rule: qbo.invoice_aging

Catch open QuickBooks invoices as they cross the 30 / 60 / 90 day-past-due
aging thresholds. Each crossing is its own escalation: the entity_id carries the
bucket (invoice:<Id>:<bucket>) so the same invoice can re-ping the owner once at
30, again at 60, again at 90 instead of being deduped after the first nag.

Loss-aversion copy: lead with the dollars on the table and how long they have
been sitting, because money you are owed and have not chased reads as money you
are losing.

Read-only. Queries QBO only through the qbo-invoicing skill's read tool
(qbo_lookup.py query ... --json), which returns a parsed JSON list of Invoice
records. Defensive: the whole body is wrapped, returns [] on any error.

House rule: zero em dashes anywhere. Periods, commas, colons, parens only.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

# Day-past-due thresholds, checked high to low so each invoice maps to the
# deepest bucket it has reached. Bucket label is part of the dedup key.
_BUCKETS = (
    (90, "90"),
    (60, "60"),
    (30, "30"),
)

# Floor so we never bother the owner over a rounding error.
_MIN_BALANCE = 250.0

RULE = RuleSpec(
    key="qbo.invoice_aging",
    title="Invoice aging (30/60/90)",
    providers=("qbo",),
    category="money_at_risk",
    cadence_minutes=240,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={"min_amount": _MIN_BALANCE},
)


def _money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "$0"


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _bucket_for(days_past_due: int):
    for threshold, label in _BUCKETS:
        if days_past_due >= threshold:
            return threshold, label
    return None


def evaluate(ctx) -> list:
    try:
        today = ctx.now.date()

        # Read-only pull of open A/R. Single QBO SQL call via the skill's read
        # tool; --json makes qbo_lookup print the raw record list we parse here.
        # NOTE on arg order: --json is a top-level flag on qbo_lookup.py's main
        # parser, not on the `query` subparser. argparse only accepts it BEFORE
        # the subcommand. Putting it after "query ..." makes qbo_lookup exit
        # non-zero, which run_skill turns into None, which would silently kill
        # this rule forever. Keep --json first.
        rows = ctx.run_skill(
            "qbo-invoicing",
            "qbo_lookup.py",
            [
                "--json",
                "query",
                "SELECT * FROM Invoice WHERE Balance > '0' "
                "ORDERBY DueDate ASC MAXRESULTS 200",
            ],
        )
        if not isinstance(rows, list):
            return []

        signals = []
        for inv in rows:
            if not isinstance(inv, dict):
                continue

            inv_id = str(inv.get("Id") or "").strip()
            if not inv_id:
                continue

            try:
                balance = float(inv.get("Balance") or 0.0)
            except (TypeError, ValueError):
                continue
            if balance < _MIN_BALANCE:
                continue

            # Age off the due date (fall back to txn date if a due date is
            # missing, which QBO allows for terms-less invoices).
            due = _parse_date(inv.get("DueDate")) or _parse_date(inv.get("TxnDate"))
            if due is None:
                continue

            days_past_due = (today - due).days
            crossed = _bucket_for(days_past_due)
            if crossed is None:
                continue
            threshold, label = crossed

            who = ""
            ref = inv.get("CustomerRef")
            if isinstance(ref, dict):
                who = str(ref.get("name") or "").strip()
            who = who or "A customer"

            doc = str(inv.get("DocNumber") or "").strip()
            doc_tag = f" (invoice #{doc})" if doc else ""

            amt = _money(balance)
            summary = (
                f"{who} still owes you {amt}{doc_tag}, now {days_past_due} days "
                f"past due. That is {amt} you earned and have not collected, and "
                f"every week past {threshold} days it gets harder to get back."
            )
            proposal = f"Chase the {amt} with a reminder and a fresh pay link?"

            signals.append(
                Signal(
                    entity_id=f"invoice:{inv_id}:{label}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="qbo.chase_overdue",
                        params={
                            "invoice_id": inv_id,
                            "bucket": label,
                            "days_past_due": days_past_due,
                            "balance": round(balance, 2),
                            "customer": who,
                        },
                    ),
                    amount=balance,
                    count=1,
                    urgency="high" if threshold >= 60 else "normal",
                )
            )

        return signals
    except Exception:
        return []
