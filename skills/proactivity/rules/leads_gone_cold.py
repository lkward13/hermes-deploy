"""Rule: leads.gone_cold (hot_leads).

A lead that went quiet. It sat in the pipeline, nobody touched it, and now it is
drifting toward dead. The fix is cheap: one nudge before the lead forgets you
exist. This rule walks the customer's connected CRM (GoHighLevel, BoldTrail, or
Podio), finds open leads whose last activity is several days stale (but not so
old they are effectively gone), and proposes a re-engage so the owner can pull
them back with one tap.

Each CRM exposes recent leads differently, so we read each the durable way and
normalize a "last touched" timestamp from whatever date field the skill returns
(updated / created / last activity). We only flag leads still in an open-ish
stage: a lead already marked won, lost, or cancelled is not cold, it is closed.

Read-only, cheap, defensive: the whole body is wrapped so any error returns []
and the engine moves on.

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use
periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

RULE = RuleSpec(
    key="leads.gone_cold",
    title="Lead gone cold",
    providers=("gohighlevel", "boldtrail", "podio"),
    category="hot_leads",
    cadence_minutes=1440,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={},
)

# A lead is "cold" once its last touch is at least this many days stale. Under
# this it is still warm and a ping is just noise. Past the upper bound the lead
# is effectively dead, not "cold", so re-engaging is a lower-value cold call and
# we leave it out of the proactive band.
_COLD_LOWER_DAYS = 5
_COLD_UPPER_DAYS = 60

# How many of the most-recent leads to scan per provider (the lists come back
# newest-first, so the cold ones live in the tail).
_SCAN_LIMIT = 100

# Stage / status tokens that mean a lead is closed (won, lost, or otherwise off
# the board). Matched as a lowercase substring so "Deal Won", "closed_lost",
# "Invoice Paid", etc. all catch. Anything not matching is treated as open.
_CLOSED_MARKERS = (
    "won", "lost", "closed", "cancel", "dead", "paid", "complete", "completed",
    "abandon", "archiv", "unqualified", "junk", "spam", "do not", "do-not",
)

# Date-ish keys we will accept as "last activity", most-specific first.
_DATE_KEYS = (
    "last_activity", "lastActivity", "lastActivityAt", "last_activity_at",
    "last_touched", "lastTouchedAt", "last_event", "lastEventOn",
    "updated", "updatedAt", "updated_at", "dateUpdated", "date_updated",
    "modified", "modifiedAt", "modified_on", "last_event_on",
    "created", "createdAt", "created_at", "dateAdded", "date_added",
)

_NAME_KEYS = (
    "full_name", "fullName", "name", "contactName", "title", "display_name",
    "displayName",
)

_STATUS_KEYS = (
    "status", "stage", "stage_name", "stageName", "pipeline_stage",
    "pipelineStage", "lead_status", "leadStatus",
)

_ID_KEYS = ("id", "ID", "contact_id", "contactId", "item_id", "itemId")


def _parse_dt(raw):
    """Parse a CRM timestamp (ISO string or epoch seconds) to aware UTC, or None."""
    if raw is None:
        return None
    # Epoch seconds (some APIs hand back unix ints).
    if isinstance(raw, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(raw), datetime.timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Podio-style "2026-06-10 14:03:11" (space separator, no tz).
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        # Last resort: a leading date like "2026-06-10".
        try:
            dt = datetime.datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _first(row, keys):
    for k in keys:
        v = row.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


def _name_of(row):
    name = _first(row, _NAME_KEYS)
    if name:
        return str(name)
    first = row.get("firstName") or row.get("first_name")
    last = row.get("lastName") or row.get("last_name")
    parts = [str(p).strip() for p in (first, last) if isinstance(p, str) and p.strip()]
    if parts:
        return " ".join(parts)
    return "A lead"


def _last_touch(row):
    for k in _DATE_KEYS:
        if k in row:
            dt = _parse_dt(row.get(k))
            if dt is not None:
                return dt
    return None


def _is_closed(row):
    for k in _STATUS_KEYS:
        v = row.get(k)
        if isinstance(v, str):
            low = v.lower()
            if any(m in low for m in _CLOSED_MARKERS):
                return True
    return False


def _fetch(ctx):
    """Pull recent leads from whichever CRM is connected. Each entry is a
    (provider, row) pair so the entity_id can be namespaced. Best-effort: a
    provider that is not connected just returns nothing from its skill."""
    out = []

    # GoHighLevel: subcommand-style CLI, no list-recent, so we read the open
    # opportunities (each carries a pipeline stage + an updated timestamp) and
    # fall back to a broad contact search. A blank query returns the location's
    # contacts on the v2 API.
    for script_args in (
        ("ghl.py", ["opportunities-search", "--json"]),
        ("ghl.py", ["contacts-search", "--query", "", "--json"]),
    ):
        rows = ctx.run_skill("gohighlevel", script_args[0], script_args[1])
        for r in _rows(rows):
            out.append(("ghl", r))
        if out:
            break

    # BoldTrail: clean list-recent with JSON.
    rows = ctx.run_skill(
        "boldtrail", "boldtrail_lookup.py",
        ["--list-recent", "--limit", str(_SCAN_LIMIT), "--json"],
    )
    for r in _rows(rows):
        out.append(("boldtrail", r))

    # Podio: list-recent with JSON.
    rows = ctx.run_skill(
        "podio", "podio_lookup.py",
        ["--list-recent", "--limit", str(_SCAN_LIMIT), "--json"],
    )
    for r in _rows(rows):
        out.append(("podio", r))

    return out


def _rows(payload):
    """Coerce a skill payload into a list of dict rows (handles a bare list or a
    {"contacts": [...]} / {"results": [...]} wrapper)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("contacts", "results", "items", "opportunities", "leads", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _days_phrase(days):
    if days == 1:
        return "1 day"
    return f"{days} days"


def evaluate(ctx) -> list:
    try:
        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)

        signals = []
        seen_ids = set()

        for provider, row in _fetch(ctx):
            lead_id = _first(row, _ID_KEYS)
            if lead_id is None:
                continue
            entity_id = f"lead:{provider}:{lead_id}"
            if entity_id in seen_ids:
                continue

            if _is_closed(row):
                continue

            touched = _last_touch(row)
            if touched is None:
                continue
            cold_days = int((now - touched).total_seconds() // 86400)
            if cold_days < _COLD_LOWER_DAYS or cold_days > _COLD_UPPER_DAYS:
                continue

            seen_ids.add(entity_id)

            name = _name_of(row)
            stage = _first(row, _STATUS_KEYS)
            stage_part = f" (sitting in {stage})" if isinstance(stage, str) and stage.strip() else ""

            summary = (
                f"{name} has gone quiet, no movement in {_days_phrase(cold_days)}{stage_part}. "
                f"Leads this cold forget you fast."
            )
            proposal = "Want me to fire off a re-engage text to warm them back up?"

            signals.append(
                Signal(
                    entity_id=entity_id,
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="leads.reengage",
                        params={
                            "provider": provider,
                            "lead_id": str(lead_id),
                            "name": name,
                            "cold_days": cold_days,
                            "stage": str(stage) if stage else "",
                        },
                    ),
                    amount=0.0,
                    count=1,
                    urgency="high" if cold_days >= 14 else "normal",
                )
            )

        return signals
    except Exception:
        return []
