"""Proactivity rule: leads.new_uncontacted (speed-to-lead).

A brand new lead just landed in the CRM and nobody has touched it yet. The single
highest-leverage move in any sales business is contacting a fresh lead fast: the
odds of connecting fall off a cliff after the first few minutes. This rule catches
"a new lead came in, you have not replied" and offers a one-tap drafted first touch.

Works across whichever lead CRM the customer connected (GoHighLevel, BoldTrail, or
Podio). The engine's provider gate fires this rule if any of those three is
connected; inside evaluate() we query each connected provider's read-only lookup
skill and normalize the results to a common shape.

Read-only by contract: the only side effect is shelling each provider's read-only
lookup script via ctx.run_skill (never a write/mutation path). The actual outreach
is the engine's job when the owner taps (action kind leads.draft_first_touch). The
whole body is wrapped in try/except and returns [] on any error (the engine
isolates failures, but we stay safe anyway).

House rule: zero em dashes anywhere. Use periods, commas, colons, parens. Pure
stdlib.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="leads.new_uncontacted",
    title="New lead, no first touch yet",
    providers=("gohighlevel", "boldtrail", "podio"),
    category="hot_leads",
    cadence_minutes=5,
    default_autonomy="draft",
    # One nudge per new lead, full stop. cooldown >= lookback means once a lead
    # is nudged it has aged out of the "new" window before the cooldown lapses,
    # so it never re-fires. (Was 1.0, which re-nagged the SAME lead every hour
    # for the whole 24h window -> up to 24 pings for one lead. That, plus owners
    # handling a lead without updating Podio's invoice_status, was the spam:
    # leads they already responded to kept re-alerting hourly.)
    cooldown_hours=26.0,
    materiality={"min_count": 1},
)

# How far back a lead can have been created and still count as "new". Speed-to-lead
# wants minutes, but we use a generous window so a lead that arrived while the agent
# was briefly down is still caught the next tick.
_LOOKBACK_HOURS = 24.0

# Junk/placeholder lead names that phone systems (CallRail etc.) drop into the CRM
# for spam, wrong numbers, and unanswered rings. Never nag the owner about these.
# Matched case-insensitively as a substring of the lead name.
_JUNK_NAME_MARKERS = (
    "wireless caller",
    "wrong number",
    "unknown caller",
    "unknown name",
    "spam",
    "scam",
    "no caller id",
    "restricted",
    "unavailable",
    "anonymous",
    "robocall",
    "telemarket",
)


def _looks_junk(name) -> bool:
    blob = str(name or "").strip().lower()
    if not blob:
        return False
    return any(marker in blob for marker in _JUNK_NAME_MARKERS)

# Substrings that, if present in a lead's tags or status, mean someone already
# reached out. Matched case-insensitively. Kept generous so a label drift does not
# make us nag about a lead that was in fact already contacted.
_CONTACTED_MARKERS = (
    "contacted",
    "replied",
    "responded",
    "called",
    "texted",
    "emailed",
    "followed up",
    "follow up",
    "follow-up",
    "spoke",
    "in progress",
    "nurtur",
    "quoted",
    "invoice",
    "won",
    "closed",
    "appointment",
    "booked",
)


def _parse_dt(value):
    """Parse a created-at timestamp into a tz-aware UTC datetime, or None.

    Tolerates ISO 8601 (with or without a trailing Z), epoch seconds/millis as a
    number or numeric string, and bare 'YYYY-MM-DD' dates."""
    if value is None:
        return None
    # Numeric epoch (seconds or milliseconds).
    if isinstance(value, (int, float)):
        secs = float(value)
        if secs > 1e12:  # milliseconds
            secs /= 1000.0
        try:
            return datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Numeric string epoch.
    if s.lstrip("-").isdigit():
        try:
            secs = float(s)
            if secs > 1e12:
                secs /= 1000.0
            return datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        # Last resort: a bare date.
        try:
            d = datetime.date.fromisoformat(s[:10])
            dt = datetime.datetime(d.year, d.month, d.day)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _is_recent(created, now):
    if created is None:
        return False
    age_hours = (now - created).total_seconds() / 3600.0
    return 0.0 <= age_hours <= _LOOKBACK_HOURS


def _looks_contacted(*texts):
    blob = " ".join(t for t in texts if isinstance(t, str)).lower()
    return any(marker in blob for marker in _CONTACTED_MARKERS)


def _tags_text(tags):
    if isinstance(tags, str):
        return tags
    if isinstance(tags, (list, tuple)):
        parts = []
        for t in tags:
            if isinstance(t, str):
                parts.append(t)
            elif isinstance(t, dict):
                parts.append(str(t.get("name") or t.get("value") or ""))
        return " ".join(parts)
    return ""


def _name_or(default, *candidates):
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return default


# ---------------------------------------------------------------------------
# Per-provider extractors. Each returns a list of normalized lead dicts:
#   {id, name, created, contacted_text}
# created is a tz-aware datetime or None; contacted_text is any tag/status blob.
# ---------------------------------------------------------------------------

def _ghl_leads(ctx):
    """GoHighLevel: contacts-search --json returns the raw LeadConnector payload
    ({"contacts": [...]}) of recent contacts. Each contact carries dateAdded,
    tags, and a name (contactName or firstName/lastName)."""
    payload = ctx.run_skill("gohighlevel", "ghl.py", ["contacts-search", "--json"])
    contacts = None
    if isinstance(payload, dict):
        contacts = payload.get("contacts")
        if contacts is None:
            contacts = payload.get("data")
    elif isinstance(payload, list):
        contacts = payload
    if not isinstance(contacts, list):
        return []
    out = []
    for c in contacts:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or c.get("contactId")
        if not cid:
            continue
        name = _name_or(
            "A new lead",
            c.get("contactName"),
            (str(c.get("firstName") or "") + " " + str(c.get("lastName") or "")).strip(),
        )
        created = _parse_dt(c.get("dateAdded") or c.get("createdAt") or c.get("dateCreated"))
        contacted_text = _tags_text(c.get("tags"))
        out.append({
            "id": str(cid),
            "name": name,
            "created": created,
            "contacted_text": contacted_text,
        })
    return out


def _boldtrail_leads(ctx):
    """BoldTrail (kvCORE): --list-recent --json returns normalized contacts with
    id, name, tags, created_at."""
    payload = ctx.run_skill("boldtrail", "boldtrail_lookup.py", ["--list-recent", "--limit", "50", "--json"])
    rows = None
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("contacts") or payload.get("data")
    elif isinstance(payload, list):
        rows = payload
    if not isinstance(rows, list):
        return []
    out = []
    for c in rows:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or c.get("contact_id")
        if not cid:
            continue
        name = _name_or("A new lead", c.get("name"))
        created = _parse_dt(c.get("created_at") or c.get("created"))
        contacted_text = _tags_text(c.get("tags"))
        out.append({
            "id": str(cid),
            "name": name,
            "created": created,
            "contacted_text": contacted_text,
        })
    return out


def _podio_leads(ctx):
    """Podio: --list-recent --json returns parsed items with item_id, name, date,
    invoice_status. A fresh item still on 'New Lead' status is uncontacted."""
    payload = ctx.run_skill("podio", "podio_lookup.py", ["--list-recent", "--limit", "50", "--json"])
    rows = payload if isinstance(payload, list) else None
    if rows is None and isinstance(payload, dict):
        rows = payload.get("results") or payload.get("items")
    if not isinstance(rows, list):
        return []
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        iid = item.get("item_id") or item.get("id")
        if not iid:
            continue
        name = _name_or("A new lead", item.get("name"), item.get("title"))
        # Use the item's REAL creation timestamp (created_on, full datetime), not
        # the "date" custom field (often date-only -> parses to midnight -> a
        # just-arrived lead would read "18 hours ago"). Fall back to date only if
        # created_on is missing.
        created = _parse_dt(item.get("created_on") or item.get("date"))
        contacted_text = str(item.get("invoice_status") or "")
        out.append({
            "id": str(iid),
            "name": name,
            "created": created,
            "contacted_text": contacted_text,
        })
    return out


_PROVIDERS = (
    ("gohighlevel", _ghl_leads),
    ("boldtrail", _boldtrail_leads),
    ("podio", _podio_leads),
)

# Owner-facing display names so the summary reads like a person wrote it, not a
# raw provider key. entity_id still uses the lowercase provider key for dedup.
_PROVIDER_LABEL = {
    "gohighlevel": "GoHighLevel",
    "boldtrail": "BoldTrail",
    "podio": "Podio",
}


def _age_phrase(created, now):
    if created is None:
        return "just now"
    mins = int((now - created).total_seconds() // 60)
    if mins <= 1:
        return "a minute ago"
    if mins < 60:
        return f"{mins} minutes ago"
    hours = mins // 60
    if hours == 1:
        return "an hour ago"
    return f"{hours} hours ago"


def evaluate(ctx):
    try:
        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        signals = []

        for provider, extractor in _PROVIDERS:
            try:
                leads = extractor(ctx)
            except Exception:
                # One provider failing must not sink the others.
                continue
            if not leads:
                continue

            for lead in leads:
                created = lead.get("created")
                if not _is_recent(created, now):
                    continue
                if _looks_contacted(lead.get("contacted_text", "")):
                    continue
                # Never nag about wrong-number / spam / placeholder leads.
                if _looks_junk(lead.get("name")):
                    continue

                lead_id = lead.get("id")
                if not lead_id:
                    continue
                who = lead.get("name") or "A new lead"
                when = _age_phrase(created, now)
                where = _PROVIDER_LABEL.get(provider, provider)

                summary = (
                    f"{who} came in {when} on {where} and nobody has reached out yet. "
                    f"First touch fast is how you win these."
                )
                proposal = "Want me to draft the first text now?"

                signals.append(
                    Signal(
                        entity_id=f"lead:{provider}:{lead_id}",
                        summary=summary,
                        proposal=proposal,
                        action=Action(
                            kind="leads.draft_first_touch",
                            params={
                                "provider": provider,
                                "lead_id": str(lead_id),
                                "lead_name": who,
                            },
                        ),
                        count=1,
                        urgency="high",
                        # Lets the owner Done/Snooze this lead by name straight
                        # from the nudge (engine builds name:<provider>:<name>).
                        meta={"provider": provider, "name": who},
                    )
                )

        return signals
    except Exception:
        return []
