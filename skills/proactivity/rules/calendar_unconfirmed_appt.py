"""Rule: calendar.unconfirmed_appt (work_today).

An appointment landing in the next few hours that has a real customer on it but
is not yet confirmed with that customer is a no-show waiting to happen. The owner
drives across town, the customer forgot, the slot is burned. This rule catches
those appointments early enough to fire off a quick "see you at 2pm?" text and
lock it in.

How we read "has a customer" and "not yet confirmed" from what the google
skill actually returns. google/gcalendar.py's read-only `list` gives each event
as {id, title, start, end, location, description, attendees, link}, where
attendees is a flat list of email strings (no per-attendee RSVP status). So:

  - "Has a customer": the event has at least one attendee email that is not the
    owner's own google account (GOOGLE_OWNER_EMAIL in the env, if present). A
    solo block with no outside attendee is the owner's own time, not a customer
    appointment, and we leave it alone.

  - "Not yet confirmed": the title or description carries no confirmation marker.
    The small-business pattern is the owner (or this agent) tags an event
    "confirmed" once the customer says yes. Until that marker is present, we
    treat the appointment as still open and worth a nudge. Tagging it via the
    one-tap action (calendar.confirm_appt) both texts the customer and stamps
    the event, so the same appointment never nags twice.

Window: only appointments starting between now and N hours out (default 4), and
never one already in progress or in the past. Cadence is 180 min and cooldown is
12h, so a 9am job flagged at 6am will not re-fire before it happens.

Read-only by contract: the only side effect is shelling the read-only `list`
command. The whole body is wrapped in try/except and returns [] on any error
(the engine isolates failures, but we stay safe regardless).

HARD HOUSE RULE: zero em dashes (the long horizontal dash) anywhere. Use periods,
commas, colons, parens.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

RULE = RuleSpec(
    key="calendar.unconfirmed_appt",
    title="Unconfirmed appointment",
    providers=("google",),
    category="work_today",
    cadence_minutes=180,
    default_autonomy="draft",
    cooldown_hours=12.0,
    materiality={},
)

# How far ahead we look. An appointment further out than this is not urgent yet;
# one inside this window with no confirmation is worth a one-tap nudge now.
_WINDOW_HOURS = 4.0

# Markers that mean the owner already locked this in with the customer. If any of
# these show up in the title or description, the appointment is confirmed and we
# stay quiet. Kept lowercase for case-insensitive matching.
_CONFIRMED_MARKERS = (
    "confirmed",
    "[confirmed]",
    "(confirmed)",
    "appt confirmed",
    "customer confirmed",
    "reconfirmed",
)


def _parse_start(s):
    """gcalendar gives 'YYYY-MM-DDTHH:MM:SS(+tz)' for timed events or
    'YYYY-MM-DD' for all-day. Return an aware UTC datetime for timed events, or
    None (all-day events have no clock time, so they cannot be "in N hours")."""
    if not s or not isinstance(s, str):
        return None
    raw = s.strip()
    if len(raw) == 10:  # all-day, date only: no time-of-day to act on
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _clock(dt) -> str:
    """A tight 12-hour clock label, e.g. '9am', '2:30pm'."""
    hour = dt.hour % 12 or 12
    ampm = "am" if dt.hour < 12 else "pm"
    if dt.minute:
        return f"{hour}:{dt.minute:02d}{ampm}"
    return f"{hour}{ampm}"


def _is_confirmed(title: str, description: str) -> bool:
    blob = (title + " " + description).lower()
    return any(marker in blob for marker in _CONFIRMED_MARKERS)


def _customer_emails(attendees, owner_email: str):
    """Attendee emails that are not the owner. These are the customers we would
    be confirming with."""
    out = []
    for a in attendees or []:
        if not isinstance(a, str):
            continue
        email = a.strip()
        if not email:
            continue
        if owner_email and email.lower() == owner_email:
            continue
        out.append(email)
    return out


def _customer_label(emails) -> str:
    """A human-ish label for the first customer email (the local part, tidied),
    so the ping reads like a name and not a raw address. Falls back to the email
    if we cannot make a clean label."""
    if not emails:
        return "the customer"
    local = emails[0].split("@", 1)[0]
    cleaned = local.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return emails[0]
    return cleaned.title()


def evaluate(ctx) -> list:
    try:
        events = ctx.run_skill(
            "google",
            "gcalendar.py",
            ["list", "--days", "1", "--max", "30"],
        )
        if not isinstance(events, list):
            return []

        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        horizon = now + datetime.timedelta(hours=_WINDOW_HOURS)

        owner_email = str(ctx.env.get("GOOGLE_OWNER_EMAIL") or "").strip().lower()

        signals = []
        for e in events:
            if not isinstance(e, dict):
                continue

            event_id = e.get("id")
            if not event_id:
                continue

            start = _parse_start(e.get("start"))
            if start is None:
                continue
            # Only appointments that have not started yet and land inside the
            # window. Skip in-progress and already-past, skip too-far-out.
            if start <= now or start > horizon:
                continue

            attendees = e.get("attendees")
            customers = _customer_emails(attendees, owner_email)
            if not customers:
                # No outside attendee: this is the owner's own block, not a
                # customer appointment. Nothing to confirm.
                continue

            title = str(e.get("title") or "(no title)").strip() or "(no title)"
            description = str(e.get("description") or "")
            if _is_confirmed(title, description):
                continue

            mins_out = int(round((start - now).total_seconds() / 60.0))
            if mins_out >= 60:
                hrs = mins_out / 60.0
                # One decimal only when it reads naturally (e.g. "1.5 hours").
                if abs(hrs - round(hrs)) < 0.05:
                    when = f"in {int(round(hrs))} hour" + ("s" if round(hrs) != 1 else "")
                else:
                    when = f"in {hrs:.1f} hours"
            elif mins_out <= 1:
                when = "in under a minute"
            else:
                when = f"in {mins_out} min"

            who = _customer_label(customers)
            loc = str(e.get("location") or "").strip()
            where = f" at {loc}" if loc else ""

            summary = (
                f'"{title}" with {who} is at {_clock(start)} ({when}){where}, '
                f"and you have not confirmed it with them yet."
            )
            proposal = f"Want me to text {who} to confirm and mark it confirmed?"

            urgency = "high" if mins_out <= 120 else "normal"

            signals.append(
                Signal(
                    entity_id=f"calendar-appt:{event_id}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="calendar.confirm_appt",
                        params={
                            "event_id": str(event_id),
                            "title": title,
                            "start": str(e.get("start") or ""),
                            "customer_email": customers[0],
                            "customer_emails": customers,
                            "location": loc,
                        },
                    ),
                    amount=0.0,
                    count=1,
                    urgency=urgency,
                )
            )

        return signals
    except Exception:
        return []
