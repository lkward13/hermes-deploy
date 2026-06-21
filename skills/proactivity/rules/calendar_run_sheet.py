"""Proactivity rule: calendar.run_sheet.

A morning run-sheet: read today's events from Google Calendar and send the owner
one plain-English summary of what their day looks like (first start, last end,
the headline jobs/appointments, how many total). Informational only, no one-tap
action: it is the "here is your day" coffee ping, not a thing to approve.

Read-only by contract: the only side effect is shelling google/gcalendar.py's
read-only `list` command. The whole body is wrapped in try/except and returns []
on any error (the engine isolates failures, but we stay safe anyway).

Dedup note: cadence is daily and cooldown is short (20h), and the entity_id is
keyed to today's calendar date, so the run-sheet fires once each new morning and
never double-pings if the tick runs again the same day.

House rule: zero em dashes anywhere. Use periods, commas, colons, parens.
"""

from __future__ import annotations

import datetime


from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="calendar.run_sheet",
    title="Today's run sheet",
    providers=("google",),
    category="work_today",
    cadence_minutes=1440,
    cooldown_hours=20.0,
    materiality={"min_count": 1},
)


def _parse_start(s):
    """Calendar gives 'YYYY-MM-DDTHH:MM:SS(+tz)' for timed events or 'YYYY-MM-DD'
    for all-day. Return (local_dt_or_None, instant_or_None, is_all_day).

    local_dt keeps the event's own wall clock so the owner sees "9am" in their
    own time. instant is the same moment normalized to UTC so we can sort and
    window every event on one consistent timeline (no mixed aware/naive blowups,
    no UTC-vs-local date drift). All-day events return (None, None, True)."""
    if not s or not isinstance(s, str):
        return None, None, False
    raw = s.strip()
    if len(raw) == 10:  # all-day, date only
        try:
            datetime.date.fromisoformat(raw)
            return None, None, True
        except ValueError:
            return None, None, False
    try:
        local_dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, None, False
    if local_dt.tzinfo is not None:
        instant = local_dt.astimezone(datetime.timezone.utc)
    else:
        # Floating time: treat the wall clock as UTC so it still sorts.
        instant = local_dt.replace(tzinfo=datetime.timezone.utc)
    return local_dt, instant, False


def _clock(dt) -> str:
    """A tight 12-hour clock label, e.g. '9am', '2:30pm'."""
    hour = dt.hour % 12 or 12
    ampm = "am" if dt.hour < 12 else "pm"
    if dt.minute:
        return f"{hour}:{dt.minute:02d}{ampm}"
    return f"{hour}{ampm}"


def _count_word(n: int) -> str:
    return "1 thing" if n == 1 else f"{n} things"


def evaluate(ctx) -> list:
    try:
        events = ctx.run_skill(
            "google",
            "gcalendar.py",
            ["list", "--days", "1", "--max", "30"],
        )
        if not isinstance(events, list):
            return []

        # The skill returns the window [now, now+1 day]. Anchor "today" off
        # ctx.now (engine supplies it in UTC) and keep timed events inside that
        # same 24h window. We window on the UTC instant, never on a local date,
        # so the run sheet never silently empties when the tick fires across UTC
        # midnight in the owner's evening.
        now = ctx.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        window_end = now + datetime.timedelta(days=1)

        timed = []   # (local_dt, instant, title, location)
        allday = []  # title

        for e in events:
            if not isinstance(e, dict):
                continue
            local_dt, instant, is_all_day = _parse_start(e.get("start"))
            title = str(e.get("title") or "(no title)").strip() or "(no title)"
            if is_all_day:
                allday.append(title)
                continue
            if instant is None or local_dt is None:
                continue
            # Keep what falls in the next 24h. Allow a small grace before "now"
            # so an event that started a few minutes ago still shows on the sheet.
            if instant < now - datetime.timedelta(minutes=15) or instant > window_end:
                continue
            loc = str(e.get("location") or "").strip()
            timed.append((local_dt, instant, title, loc))

        total = len(timed) + len(allday)
        if total == 0:
            return []

        timed.sort(key=lambda t: t[1])

        # Headline: the day's time range, but only when there is more than one
        # timed stop. A single event already prints its own time in the named
        # list below, so a "(9am)" headline would just repeat it.
        parts = []
        if len(timed) > 1:
            parts.append(f"{_clock(timed[0][0])} to {_clock(timed[-1][0])}")

        # Name the first up-to-three stops with their times so it reads like a
        # real run sheet, not a count.
        named = []
        for local_dt, _instant, title, loc in timed[:3]:
            tag = f"{_clock(local_dt)} {title}"
            if loc:
                tag += f" ({loc})"
            named.append(tag)
        more = len(timed) - len(named)

        bits = []
        if named:
            bits.append(", ".join(named))
        if more > 0:
            bits.append(f"plus {more} more")
        if allday:
            bits.append(", ".join(allday[:2]) + (f" plus {len(allday) - 2} more all-day" if len(allday) > 2 else ""))

        lead = f"Today: {_count_word(total)} on your calendar"
        if parts:
            lead += f" ({parts[0]})"
        body = ". ".join([lead] + bits) + "."

        return [
            Signal(
                entity_id=f"run_sheet:{now.date().isoformat()}",
                summary=body,
                proposal="",
                action=Action(kind=""),
                amount=0.0,
                count=total,
                urgency="normal",
            )
        ]
    except Exception:
        return []
