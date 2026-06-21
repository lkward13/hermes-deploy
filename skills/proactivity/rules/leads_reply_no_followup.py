"""Proactivity rule: leads.reply_no_followup (hot_leads).

A lead texted back and then nothing happened. The single most expensive silence
in a small business is a warm lead who replied while the owner was on a roof, in
a truck, or asleep, and never got an answer. Speed to lead is the whole game:
the reply is the buying signal, and every hour it sits unanswered the lead cools
and shops your competitor. This rule catches conversations where the LAST message
was from the lead (inbound) and the owner has not responded in N hours, so we can
hand the owner a one tap drafted reply before the deal walks.

Signal source: GoHighLevel conversations. GHL is the provider in this rule's gate
that actually carries two way message threads with a direction on each message
(inbound = the lead, outbound = the owner/agent), which is exactly what "they
replied and we went quiet" needs. We call the read only ``ghl.py conversations``
command with no contact filter, which returns the location's recent conversations
(each with lastMessageDirection + lastMessageDate), and flag the ones where the
newest message is inbound and older than the follow up window. BoldTrail and
Podio are kept in the provider gate so the rule still arms for a customer who runs
their pipeline there and has GHL wired for messaging, but the durable reply signal
comes from GHL.

Read only by contract: the only side effect is subprocessing GHL's read only
conversations lookup. The whole body is wrapped in try/except and returns [] on
any error (the engine isolates failures, but we stay safe anyway).

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use periods,
commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="leads.reply_no_followup",
    title="Lead replied, no follow up",
    providers=("gohighlevel", "boldtrail", "podio"),
    category="hot_leads",
    cadence_minutes=30,
    default_autonomy="draft",
    cooldown_hours=12.0,
    materiality={},
)

# How long an inbound reply can sit unanswered before it is worth a ping. Short,
# because this is a hot lead: 4 hours is past "stepped away for a minute" and
# squarely into "we are losing them".
_FOLLOWUP_WINDOW_HOURS = 4.0

# Stop nagging about ancient threads. Past this the lead is cold, not "waiting on
# a reply", and a 5 day old unanswered text is a different (lost lead) problem.
_STALE_CUTOFF_HOURS = 120.0

# GHL lastMessageDirection values that mean the newest message came FROM the lead.
_INBOUND = {"inbound", "in", "incoming"}


def _parse_ghl_ts(raw):
    """Coerce a GHL lastMessageDate into epoch milliseconds, or None.

    GHL has shipped this field as epoch milliseconds (number or numeric string)
    and, on some shapes, as an ISO 8601 string. Handle both so a format change on
    their side does not silently blind the rule.
    """
    if raw is None:
        return None
    # Numeric epoch (ms if large, s if small) or numeric string.
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
        if val <= 0:
            return None
        # Heuristic: seconds-scale epoch (~1e9) vs ms-scale (~1e12).
        return val * 1000.0 if val < 1e11 else val
    # ISO 8601 string.
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp() * 1000.0
    return None


def _lead_name(conv) -> str:
    name = ""
    for key in ("contactName", "fullName", "name"):
        v = conv.get(key)
        if isinstance(v, str) and v.strip():
            name = v.strip()
            break
    if not name:
        first = (conv.get("firstName") or "").strip() if isinstance(conv.get("firstName"), str) else ""
        last = (conv.get("lastName") or "").strip() if isinstance(conv.get("lastName"), str) else ""
        name = (first + " " + last).strip()
    return name or "A lead"


def _waited_phrase(hours: float) -> str:
    if hours >= 48:
        days = int(round(hours / 24.0))
        return f"{days} days ago"
    h = int(round(hours))
    if h <= 1:
        return "about an hour ago"
    return f"{h} hours ago"


def evaluate(ctx) -> list:
    try:
        # No --contact-id: returns the location's recent conversations, each
        # carrying lastMessageDirection + lastMessageDate.
        data = ctx.run_skill("gohighlevel", "ghl.py", ["conversations", "--json"])
        if not isinstance(data, dict):
            return []

        convs = data.get("conversations")
        if not isinstance(convs, list):
            convs = data.get("data") if isinstance(data.get("data"), list) else []
        if not isinstance(convs, list):
            return []

        now_ms = ctx.now.timestamp() * 1000.0
        window_ms = _FOLLOWUP_WINDOW_HOURS * 3600.0 * 1000.0
        stale_ms = _STALE_CUTOFF_HOURS * 3600.0 * 1000.0

        signals = []
        for conv in convs:
            if not isinstance(conv, dict):
                continue

            # The newest message must be FROM the lead (inbound). If the owner
            # already replied, the last message is outbound and this is handled.
            direction = str(conv.get("lastMessageDirection") or "").strip().lower()
            if direction not in _INBOUND:
                continue

            last_ms = _parse_ghl_ts(conv.get("lastMessageDate"))
            if last_ms is None:
                continue

            age_ms = now_ms - last_ms
            # Not yet past the follow up window (still "just came in"), or so old
            # the lead is cold rather than waiting: skip either way.
            if age_ms < window_ms or age_ms > stale_ms:
                continue

            conv_id = str(conv.get("id") or "").strip()
            if not conv_id:
                continue

            contact_id = str(conv.get("contactId") or "").strip()
            name = _lead_name(conv)
            waited = _waited_phrase(age_ms / 3600000.0)

            last_body = conv.get("lastMessageBody")
            last_body = last_body.strip() if isinstance(last_body, str) else ""
            if len(last_body) > 80:
                last_body = last_body[:77].rstrip() + "..."
            quote = f' They said: "{last_body}".' if last_body else ""

            summary = (
                f"{name} replied {waited} and we never wrote back.{quote} "
                f"Hot leads go cold fast."
            )

            signals.append(
                Signal(
                    entity_id=f"ghl-conversation:{conv_id}",
                    summary=summary,
                    proposal="Want me to draft a reply to send them now?",
                    action=Action(
                        kind="leads.draft_reply",
                        params={
                            "provider": "gohighlevel",
                            "conversation_id": conv_id,
                            "contact_id": contact_id,
                            "lead_name": name,
                            "last_message": last_body,
                        },
                    ),
                    amount=0.0,
                    count=1,
                    urgency="high",
                )
            )

        return signals
    except Exception:
        return []
