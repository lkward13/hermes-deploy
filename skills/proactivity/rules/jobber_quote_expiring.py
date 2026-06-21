"""Rule: jobber.quote_expiring (money_at_risk).

An open Jobber quote that the client has not accepted is a deal hanging by a
thread. Jobber quotes carry a default validity window, and a quote left in
``awaiting_response`` quietly goes stale: the client cools off, the job slips,
the money walks. This rule catches quotes that are aging toward the end of that
window and still unaccepted, so the owner can nudge before the lead goes cold.

The live Jobber GraphQL API does not expose a hard per-quote expiry date, so we
detect the same risk the durable way: a quote still sitting in
``awaiting_response`` (sent, not approved, not converted, not archived) that has
aged into the tail of the typical 30 day validity window. Read-only, cheap,
defensive: any error returns [] and the engine moves on.

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use
periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

RULE = RuleSpec(
    key="jobber.quote_expiring",
    title="Quote about to expire",
    providers=("jobber",),
    category="money_at_risk",
    cadence_minutes=720,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={"min_amount": 500.0},
)

# Jobber quotes default to a 30 day validity. We treat a still-open quote as
# "expiring soon" once it lands in the tail of that window (roughly the last
# 9 days before a 30 day window lapses), with a few days of grace past 30 so we
# still flag ones that just slipped. Under that band the quote is fresh and not
# worth a ping; far past it the deal is effectively dead, not "expiring".
_EXPIRING_LOWER_DAYS = 21
_EXPIRING_UPPER_DAYS = 35

# Jobber quoteStatus values that mean "sent to the client, awaiting their yes".
# Anything else (approved, converted, archived, draft) is not at-risk-and-open.
_OPEN_STATUSES = {"awaiting_response", "changes_requested"}


def _parse_dt(raw):
    """Parse a Jobber ISO timestamp to an aware UTC datetime, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


def _client_name(node) -> str:
    client = node.get("client") or {}
    name = (client.get("name") or {}).get("full") if isinstance(client.get("name"), dict) else None
    name = (name or "").strip()
    return name or "A client"


def evaluate(ctx) -> list:
    try:
        rows = ctx.run_skill("jobber", "jobber_lookup.py", ["quotes", "--json", "--limit", "100"])
        if not isinstance(rows, list):
            return []

        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        signals = []
        for node in rows:
            # Per-node isolation: one malformed quote never sinks the others.
            try:
                if not isinstance(node, dict):
                    continue

                status = str(node.get("quoteStatus") or "").strip().lower()
                if status not in _OPEN_STATUSES:
                    continue

                quote_id = node.get("id")
                if not quote_id:
                    continue

                created = _parse_dt(node.get("createdAt"))
                if created is None:
                    continue
                age_days = (now - created).total_seconds() / 86400.0
                if age_days < _EXPIRING_LOWER_DAYS or age_days > _EXPIRING_UPPER_DAYS:
                    continue

                try:
                    amount = float(node.get("total") or 0.0)
                except (TypeError, ValueError):
                    amount = 0.0

                # Days left in the assumed 30 day window (clamped at 0).
                days_left = int(round(30 - age_days))
                if days_left < 0:
                    days_left = 0

                client = _client_name(node)
                number = node.get("quoteNumber")
                label = f"Quote #{number}" if number else "A quote"
                title = (node.get("title") or "").strip()
                for_part = f" for {title}" if title else ""

                if days_left <= 0:
                    window = "the validity window is up"
                elif days_left == 1:
                    window = "expires in 1 day"
                else:
                    window = f"expires in {days_left} days"

                summary = (
                    f"{label}{for_part} to {client} is {_money(amount)} and still not accepted, "
                    f"{window}. They have been sitting on it for {int(round(age_days))} days."
                )
                proposal = "Want me to send them a friendly nudge before it lapses?"

                signals.append(
                    Signal(
                        entity_id=f"jobber-quote:{quote_id}",
                        summary=summary,
                        proposal=proposal,
                        action=Action(
                            kind="jobber.follow_up_quote",
                            params={
                                "quote_id": str(quote_id),
                                "quote_number": str(number) if number else "",
                                "client": client,
                                "amount": amount,
                            },
                        ),
                        amount=amount,
                        count=1,
                        urgency="high" if days_left <= 3 else "normal",
                    )
                )
            except Exception:
                continue

        return signals
    except Exception:
        return []
