"""Rule: boldtrail.hot_signal (hot_leads).

A real-estate lead who is actively shopping is a lead you call NOW, not tomorrow.
In BoldTrail (kvCORE) the platform watches what a contact does on the IDX site,
viewing listings, opening your emails, coming back day after day, and stamps that
behavior onto the contact as hashtags ("Hot Lead", "viewing-listings", "active",
"high-engagement", and friends) while bumping the contact's updated_at every time
they move. That behavior is the buying signal. The agent who calls a hot lead in
the first few minutes wins the deal; the one who waits a day loses it.

The agent-side BoldTrail skill (skills/boldtrail/boldtrail_lookup.py) exposes
contacts via "--list-recent --json", which prints a list of normalized contacts:
{id, name, email, phone, tags, created_at, updated_at}. kvCORE does not hand us a
per-contact "listing views in the last hour" counter through that script, so we
detect the same hot behavior the durable way the skill already gives us: a
behavioral hot/engagement hashtag on the contact PLUS a fresh updated_at (the
contact moved recently). Tag says hot, clock says now, that is a call.

Read-only, cheap, defensive: any error returns [] and the engine moves on.

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use periods,
commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

RULE = RuleSpec(
    key="boldtrail.hot_signal",
    title="Hot real-estate lead",
    providers=("boldtrail",),
    category="hot_leads",
    cadence_minutes=60,
    default_autonomy="draft",
    cooldown_hours=24.0,
    materiality={},
)

# How fresh the contact's last movement must be to count as "right now" hot. A
# behavioral tag that has not moved in a week is a warm lead, not a call-this-
# minute one, so we only fire while the activity is fresh.
_FRESH_WINDOW_DAYS = 2.0

# Substrings (lowercased) that, when found in a contact's hashtags, mean BoldTrail
# saw real buying behavior: listing views, repeated opens, site activity. kvCORE's
# exact label casing varies by account, so we match on substrings, not equality.
_HOT_TAG_HINTS = (
    "hot",
    "viewing-listing",
    "viewing listing",
    "viewed-listing",
    "viewed listing",
    "listing-view",
    "listing view",
    "high-engagement",
    "high engagement",
    "engaged",
    "active-buyer",
    "active buyer",
    "repeat-visit",
    "repeat visit",
    "frequent-visitor",
    "frequent visitor",
    "ready-to-buy",
    "ready to buy",
)


def _parse_dt(raw):
    """Parse a kvCORE timestamp to an aware UTC datetime, or None. Handles ISO
    strings (with or without a trailing Z) defensively."""
    if not isinstance(raw, str) or not raw.strip():
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


def _tags(contact):
    """Return the contact's tags as a list of strings, however they came back."""
    raw = contact.get("tags")
    if isinstance(raw, list):
        return [str(t) for t in raw if t is not None]
    if isinstance(raw, str) and raw.strip():
        return [raw]
    return []


def _hot_tags(tags):
    """The subset of tags that read as a buying signal (matched display strings)."""
    hits = []
    for t in tags:
        low = t.lower()
        if any(h in low for h in _HOT_TAG_HINTS):
            hits.append(t.strip())
    return hits


def _name(contact):
    nm = (contact.get("name") or "").strip()
    return nm or "A lead"


def _contact_line(contact):
    """How to reach them, for the owner-facing line."""
    phone = (contact.get("phone") or "").strip()
    email = (contact.get("email") or "").strip()
    if phone:
        return phone
    if email:
        return email
    return ""


def _humanize_age(days):
    """A plain age phrase for how recently the lead moved."""
    if days < (1.0 / 24.0):
        return "in the last hour"
    if days < 1.0:
        hours = int(round(days * 24)) or 1
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    whole = int(round(days))
    return "today" if whole == 0 else ("yesterday" if whole == 1 else f"{whole} days ago")


def evaluate(ctx) -> list:
    try:
        rows = ctx.run_skill(
            "boldtrail", "boldtrail_lookup.py", ["--list-recent", "--limit", "100", "--json"]
        )
        if not isinstance(rows, list):
            return []

        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        signals = []
        for contact in rows:
            if not isinstance(contact, dict):
                continue

            cid = contact.get("id")
            if cid in (None, ""):
                continue

            hot = _hot_tags(_tags(contact))
            if not hot:
                continue

            # Freshness gate: the contact must have moved recently. We prefer
            # updated_at (kvCORE bumps it on activity), falling back to created_at
            # for a brand-new lead that came in already flagged hot.
            moved = _parse_dt(contact.get("updated_at")) or _parse_dt(contact.get("created_at"))
            if moved is None:
                continue
            age_days = (now - moved).total_seconds() / 86400.0
            if age_days < 0:
                age_days = 0.0
            if age_days > _FRESH_WINDOW_DAYS:
                continue

            name = _name(contact)
            reach = _contact_line(contact)
            reach_part = f" ({reach})" if reach else ""
            tag_part = hot[0] if len(hot) == 1 else f"{hot[0]} plus {len(hot) - 1} more"
            when = _humanize_age(age_days)

            summary = (
                f"{name}{reach_part} is going hot in BoldTrail: tagged {tag_part}, "
                f"last active {when}. They are shopping right now."
            )
            proposal = "Want me to put them at the top of your call list and pull their record?"

            signals.append(
                Signal(
                    # Day-bucketed entity so a still-hot lead can re-surface on a
                    # later day past the 24h cooldown, but never twice the same day.
                    entity_id=f"boldtrail-hot:{cid}:{now.date().isoformat()}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="leads.call_now",
                        params={
                            "provider": "boldtrail",
                            "contact_id": str(cid),
                            "name": name,
                            "phone": (contact.get("phone") or "").strip(),
                            "email": (contact.get("email") or "").strip(),
                            "hot_tags": hot,
                        },
                    ),
                    amount=0.0,
                    count=len(hot),
                    urgency="high" if age_days <= 1.0 else "normal",
                )
            )

        return signals
    except Exception:
        return []
