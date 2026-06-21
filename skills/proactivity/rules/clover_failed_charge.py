"""Proactivity rule: clover.failed_charge.

Catch a charge that got declined or failed at the Clover register so the owner
can ask for another card before the customer walks out the door. One Signal per
failed payment, ranked by the dollar amount that did not clear, with a one-tap
"retry the charge" action.

Read-only by contract: the only side effect is shelling clover's read-only
clover_lookup.py --list-payments script. The whole body is wrapped in
try/except and returns [] on any error (the engine isolates failures, but we
stay safe anyway).

House rule: zero em dashes anywhere. Use periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="clover.failed_charge",
    title="Failed charge at the register",
    providers=("clover",),
    category="money_at_risk",
    cadence_minutes=60,
    cooldown_hours=24.0,
    materiality={},
)

# Clover payment.result values that mean the money did NOT land. SUCCESS is the
# only clean clear. VOIDED/VOID are deliberate cancellations/refunds (the skill
# already treats those as refunds, not failures), so they are not a "failed
# charge" the owner needs to chase.
_FAILED_RESULTS = {"FAIL", "FAILED", "DECLINED", "DECLINE", "ERROR", "REJECTED"}

# Only surface charges that failed recently. A two hour window comfortably
# covers the 60 minute cadence (plus late ticks / missed runs) without dredging
# up stale declines the owner already handled.
_RECENT_WINDOW_S = 2 * 3600


def _money(cents) -> str:
    try:
        v = int(cents) / 100.0
    except (TypeError, ValueError):
        return "$0"
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


def _dollars(cents) -> float:
    try:
        return int(cents) / 100.0
    except (TypeError, ValueError):
        return 0.0


def evaluate(ctx) -> list:
    try:
        payments = ctx.run_skill(
            "clover",
            "clover_lookup.py",
            ["--list-payments", "--limit", "50", "--json"],
        )
        if not isinstance(payments, list):
            return []

        now_ms = ctx.now.timestamp() * 1000.0
        signals = []

        for p in payments:
            if not isinstance(p, dict):
                continue

            result = str(p.get("result") or "").strip().upper()
            if result not in _FAILED_RESULTS:
                continue

            pay_id = str(p.get("id") or "").strip()
            if not pay_id:
                continue

            created = p.get("createdTime")
            try:
                created_ms = float(created)
            except (TypeError, ValueError):
                created_ms = 0.0
            # Skip anything older than the recent window (and anything with no
            # timestamp, which we cannot place in time).
            if created_ms <= 0 or (now_ms - created_ms) > _RECENT_WINDOW_S * 1000.0:
                continue

            amount = _dollars(p.get("amount"))
            card = str((p.get("tender") or {}).get("label") or "").strip()
            how = f" on {card}" if card else ""
            verb = "declined" if result.startswith("DECLIN") else "failed"

            summary = (
                f"A {_money(p.get('amount'))} charge {verb}{how} at the register. "
                f"The customer may still be standing there."
            )

            signals.append(
                Signal(
                    entity_id=f"payment:{pay_id}",
                    summary=summary,
                    proposal="Want me to retry the charge?",
                    action=Action(
                        kind="clover.retry_charge",
                        params={"payment_id": pay_id},
                    ),
                    amount=amount,
                    count=1,
                    urgency="high",
                )
            )

        return signals
    except Exception:
        return []
