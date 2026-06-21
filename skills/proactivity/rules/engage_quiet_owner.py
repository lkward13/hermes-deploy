"""Rule: engage.quiet_owner (pulse).

The gentle one. If the owner has gone quiet for a few days, send a single warm
re-engage with one concrete, useful thing to come back for. Not a nag, not a
guilt trip, not a daily drip. One soft tap on the shoulder, then it stays out of
the way (a stable per-week entity_id plus the 72h cooldown guarantee it stays
rare even though it evaluates daily).

No provider gate (providers=()), so this rule always runs. That means it can
never assume any integration is connected. It detects quietness purely from the
agent's own filesystem (read-only, pure stdlib), and it names a concrete thing
to come back for off whatever the owner actually connected (best-effort, via the
opener's capability detection). When nothing is connected, it falls back to a
plain warm catch-up offer. The summary always carries the real number of days
quiet, never a vague "a while".

How we measure "quiet" without a provider, in order of trust, all best-effort:
  1. Newest mtime among the gateway transcript files (~/.hermes/sessions/*.jsonl).
     The gateway appends to these every owner turn, so the freshest one is a
     faithful "last time the owner talked to me" clock.
  2. The largest last_active / started_at in the sessions routing index
     (~/.hermes/sessions/sessions.json), if present.
  3. The mtime of the canonical session DB (~/.hermes/state.db) as a floor.
We take the MOST RECENT of these (most generous read of activity) so we never
re-engage someone who is in fact active. If we cannot read any of them we stay
silent: better no ping than a wrong one.

Read-only, cheap, defensive: the entire body is wrapped and returns [] on any
error (the engine isolates failures too, but we stay safe regardless).

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use
periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime
import json

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="engage.quiet_owner",
    title="Quiet owner re-engage",
    providers=(),                          # empty: always runs (no provider gate)
    category="pulse",
    cadence_minutes=1440,                  # evaluate once a day
    default_autonomy="draft",              # warm proposal, never auto-run
    cooldown_hours=72.0,                   # at most one re-engage every 3 days
    materiality={},                        # nothing to floor: it is a check-in
)


# The quiet band. Under the lower bound the owner is still around and a ping is
# just noise. Past the upper bound the account is dormant, not merely quiet, and
# one stable weekly re-engage is enough (firing daily into a churned account is
# the naggy behavior this rule exists to avoid).
_QUIET_LOWER_DAYS = 3
_QUIET_UPPER_DAYS = 21

# Friendly labels for the one concrete thing, keyed by the opener's provider id.
# A connected provider lets us offer a SPECIFIC recap instead of a generic one.
_PROVIDER_LABEL = {
    "qbo": "QuickBooks",
    "jobber": "Jobber",
    "jobnimbus": "JobNimbus",
    "clover": "Clover",
    "boldtrail": "BoldTrail",
    "gohighlevel": "GoHighLevel",
    "podio": "Podio",
    "google": "Gmail",
    "facebook": "Facebook leads",
}

# Order we prefer to name a provider in (money first, then leads, then inbox), so
# the one concrete thing we dangle is the most useful one available.
_PROVIDER_PRIORITY = (
    "qbo", "jobber", "jobnimbus", "clover",
    "boldtrail", "gohighlevel", "podio",
    "facebook", "google",
)


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _ts_to_dt(value):
    """Epoch seconds (int/float, or numeric string) -> aware UTC datetime, or None."""
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return None
    if secs <= 0:
        return None
    # Some indexes store milliseconds. A value far in the future as seconds is
    # almost certainly ms, so scale it down.
    if secs > 1e12:
        secs = secs / 1000.0
    try:
        return datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _newest_transcript_mtime(sessions_dir):
    """Most recent mtime across the gateway *.jsonl transcripts, or None."""
    newest = None
    try:
        if not sessions_dir.is_dir():
            return None
        for path in sessions_dir.glob("*.jsonl"):
            try:
                m = path.stat().st_mtime
            except OSError:
                continue
            if newest is None or m > newest:
                newest = m
    except Exception:
        return None
    return _ts_to_dt(newest) if newest is not None else None


def _index_last_active(sessions_dir):
    """Largest last_active / started_at in sessions.json, or None."""
    try:
        index = sessions_dir / "sessions.json"
        if not index.is_file():
            return None
        data = json.loads(index.read_text("utf-8"))
    except Exception:
        return None

    # The index has been a list of session dicts and (in older installs) a dict
    # keyed by session id. Handle both, plus a {"sessions": [...]} wrapper.
    rows = []
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        inner = data.get("sessions")
        if isinstance(inner, list):
            rows = [r for r in inner if isinstance(r, dict)]
        else:
            rows = [r for r in data.values() if isinstance(r, dict)]

    best = None
    for r in rows:
        for key in ("last_active", "updated_at", "started_at", "created_at"):
            dt = _ts_to_dt(r.get(key))
            if dt is not None and (best is None or dt > best):
                best = dt
    return best


def _state_db_mtime(home):
    try:
        db = home / "state.db"
        if db.is_file():
            return _ts_to_dt(db.stat().st_mtime)
    except Exception:
        return None
    return None


def _last_owner_activity(ctx):
    """Most generous (most recent) read of when the owner was last active, or
    None if we genuinely cannot tell (in which case the rule stays silent)."""
    home = ctx.home
    sessions_dir = home / "sessions"
    candidates = [
        _newest_transcript_mtime(sessions_dir),
        _index_last_active(sessions_dir),
        _state_db_mtime(home),
    ]
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        return None
    return max(candidates)


def _connected_provider_phrase(ctx):
    """Name the single most useful connected provider for the concrete offer,
    or '' if we cannot tell / nothing is connected. Best-effort, never raises."""
    try:
        from hermes_cli import nodesk_opener  # local import: keep load defensive
        caps = nodesk_opener.detect_capabilities(env=ctx.env)
        connected = set(caps.get("connected") or [])
    except Exception:
        return ""
    for provider in _PROVIDER_PRIORITY:
        if provider in connected:
            return _PROVIDER_LABEL.get(provider, provider)
    return ""


def _days_phrase(days):
    return "1 day" if days == 1 else "{} days".format(days)


def evaluate(ctx) -> list:
    try:
        now = _as_utc(ctx.now) or datetime.datetime.now(datetime.timezone.utc)

        last = _last_owner_activity(ctx)
        if last is None:
            # No trustworthy signal: stay silent rather than guess.
            return []

        quiet_days = int((now - last).total_seconds() // 86400)
        if quiet_days < _QUIET_LOWER_DAYS or quiet_days > _QUIET_UPPER_DAYS:
            return []

        # The concrete, useful thing. If a money/leads/inbox provider is wired
        # up, dangle a specific recap off it. Otherwise keep it warm and generic.
        provider = _connected_provider_phrase(ctx)
        if provider:
            proposal = (
                "Want a quick 30-second recap of what moved in your {} "
                "while you were heads-down?".format(provider)
            )
        else:
            proposal = (
                "Want me to pull together a quick recap of anything worth a "
                "look so you are caught up in 30 seconds?"
            )

        summary = (
            "Been quiet on your end for {}. No fires, just checking in.".format(
                _days_phrase(quiet_days)
            )
        )

        # Stable per-ISO-week entity_id: even though this evaluates daily, the
        # key only changes once a week, so dedup plus the 72h cooldown make a
        # repeat re-engage genuinely rare. This is the "never naggy" guarantee.
        iso = now.isocalendar()
        week_key = "{:04d}W{:02d}".format(iso[0], iso[1])

        return [
            Signal(
                entity_id="engage:quiet_owner:{}".format(week_key),
                summary=summary,
                proposal=proposal,
                action=Action(kind=""),   # informational, warm, no auto-action
                amount=0.0,
                count=quiet_days,
                urgency="low",
            )
        ]
    except Exception:
        return []
