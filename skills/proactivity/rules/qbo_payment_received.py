"""Proactivity rule: qbo.payment_received.

The good-news ping. When a sizable invoice gets paid in QuickBooks, tell the
owner so they feel the win the moment the money lands ("Coastal just paid
$1,900"). One Signal per Payment, ranked by amount. Informational only: no
one-tap action, just a quick celebratory note.

Read-only by contract: the only side effect is shelling qbo-invoicing's
read-only lookup script. The whole body is wrapped in try/except and returns
[] on any error (the engine isolates failures, but we stay safe anyway).

Dedup is by entity_id "payment:<id>" over the rule cooldown, so a payment is
celebrated exactly once. We also bound the query to payments recorded in the
last couple of days so the ping is always fresh, never a stale backfill.

House rule: zero em dashes anywhere. Use periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="qbo.payment_received",
    title="Payment received",
    providers=("qbo",),
    category="collect_now",
    cadence_minutes=120,
    cooldown_hours=24.0,
    materiality={"min_amount": 250.0},
)

# Only celebrate payments recorded in this lookback window. The query orders by
# TxnDate desc so we see the freshest first; this keeps the result set small and
# stops us from ever pinging an old payment that predates the engine.
_LOOKBACK_DAYS = 2


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


def evaluate(ctx) -> list:
    try:
        today = ctx.now.date()
        since = today - datetime.timedelta(days=_LOOKBACK_DAYS)

        records = ctx.run_skill(
            "qbo-invoicing",
            "qbo_lookup.py",
            [
                # --json is a top-level flag on qbo_lookup.py and argparse only
                # accepts it BEFORE the subcommand. Put it after "query" and
                # argparse exits 2, run_skill returns None, and this rule goes
                # silently dead. Order matters: flag first, then subcommand.
                "--json",
                "query",
                (
                    "SELECT * FROM Payment "
                    f"WHERE TxnDate >= '{since.isoformat()}' "
                    "ORDERBY TxnDate DESC MAXRESULTS 50"
                ),
            ],
        )
        if not isinstance(records, list):
            return []

        signals = []

        for r in records:
            if not isinstance(r, dict):
                continue

            amount = _to_float(r.get("TotalAmt"))
            if amount <= 0:
                continue

            pay_id = str(r.get("Id") or "").strip()
            if not pay_id:
                continue

            paid_on = _parse_date(r.get("TxnDate"))
            if paid_on is None or paid_on < since:
                continue

            who = (r.get("CustomerRef") or {}).get("name") or "A customer"

            summary = f"{who} just paid {_money(amount)}. Money's in."

            signals.append(
                Signal(
                    entity_id=f"payment:{pay_id}",
                    summary=summary,
                    proposal="",
                    action=Action(),
                    amount=amount,
                    count=1,
                    urgency="normal",
                )
            )

        return signals
    except Exception:
        return []
