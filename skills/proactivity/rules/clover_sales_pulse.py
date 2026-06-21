"""Rule: clover.sales_pulse.

A once-a-day "how's today going" pulse off the Clover POS. Compares today's
takings against a typical same weekday (the median of the last several of that
weekday) and names today's top seller, so the owner gets one punchy line like
"$2,140 today, about 30% above a normal Tuesday. Top seller: Full Detail."

Informational only: no action, no proposal, no token writes. Read-only and
defensive. The whole body is wrapped so a flaky Clover call or odd payload can
never sink the engine tick (the engine isolates failures too, but be safe).

Two read-only skill calls, both via ctx.run_skill:
  - clover_lookup.py --sales-summary --from <D> --to <D> --json
      -> list of raw Clover payment objects. Each has:
         amount      (integer cents)
         result      (skip "VOIDED"/"VOID")
         createdTime (epoch milliseconds)
  - clover_lookup.py --top-services --from <today> --to <today> --json
      -> list of {"name", "count", "revenue"} already ranked by revenue desc;
         revenue is in cents.

We pull one sales-summary spanning today plus the prior 5 weeks, then bucket by
local-ish day to get today's revenue and a same-weekday baseline in a single
call. The baseline is the median of prior same-weekday days that actually had
sales (a quiet/closed day should not drag a "normal" day to zero).

House rule: zero em dashes anywhere. Periods, commas, colons, parens only.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action

# How many weeks of history to scan for the same-weekday baseline.
_BASELINE_WEEKS = 5
# Minimum prior same-weekday days (with sales) before we trust a comparison.
_MIN_BASELINE_DAYS = 2
# Only call out an above/below day when the swing is at least this fraction,
# so normal day-to-day noise does not generate a ping.
_NOTABLE_SWING = 0.15
# Voided / refunded results to exclude from revenue (mirrors the skill).
_VOID_RESULTS = ("VOIDED", "VOID")

_WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)

RULE = RuleSpec(
    key="clover.sales_pulse",
    title="Sales pulse",
    providers=("clover",),
    category="pulse",
    cadence_minutes=1440,                 # once a day
    default_autonomy="draft",
    cooldown_hours=20.0,                   # at most one pulse per day, never twice
    materiality={},                        # informational: no floors
)


def _fmt_amount(cents):
    """'$2,140' for whole dollars, '$2,140.50' otherwise. Input is cents."""
    try:
        dollars = float(cents) / 100.0
    except (TypeError, ValueError):
        return "$" + str(cents)
    if dollars.is_integer():
        return "${:,.0f}".format(dollars)
    return "${:,.2f}".format(dollars)


def _median(values):
    """Median of a non-empty list of numbers."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _day_key(created_ms):
    """Epoch-ms -> 'YYYY-MM-DD' using UTC, matching the skill's bucketing."""
    try:
        ms = int(created_ms)
    except (TypeError, ValueError):
        return None
    try:
        dt = datetime.datetime.utcfromtimestamp(ms / 1000.0)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.date().isoformat()


def evaluate(ctx) -> list:
    try:
        today = ctx.now.date()
        today_key = today.isoformat()
        from_date = (today - datetime.timedelta(weeks=_BASELINE_WEEKS)).isoformat()

        payments = ctx.run_skill(
            "clover",
            "clover_lookup.py",
            ["--sales-summary", "--from", from_date, "--to", today_key, "--json"],
        )
        if not isinstance(payments, list):
            return []

        # Bucket non-voided revenue (cents) by day.
        by_day = {}
        for p in payments:
            if not isinstance(p, dict):
                continue
            if str(p.get("result") or "").upper() in _VOID_RESULTS:
                continue
            day = _day_key(p.get("createdTime"))
            if day is None:
                continue
            try:
                amt = int(p.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            by_day[day] = by_day.get(day, 0) + amt

        today_cents = by_day.get(today_key, 0)
        if today_cents <= 0:
            # Nothing rung up yet today: not worth a pulse.
            return []

        # Same-weekday baseline from prior weeks (skip today, skip zero-sale days).
        target_weekday = today.weekday()
        baseline_days = []
        for day_str, cents in by_day.items():
            if day_str == today_key:
                continue
            try:
                d = datetime.date.fromisoformat(day_str)
            except (ValueError, TypeError):
                continue
            if d.weekday() == target_weekday and cents > 0:
                baseline_days.append(cents)

        weekday_name = _WEEKDAY_NAMES[target_weekday]
        today_str = _fmt_amount(today_cents)

        if len(baseline_days) >= _MIN_BASELINE_DAYS:
            typical = _median(baseline_days)
            if typical > 0:
                swing = (today_cents - typical) / typical
            else:
                swing = 0.0
            pct = int(round(abs(swing) * 100))
            if swing >= _NOTABLE_SWING:
                pulse = "{amt} today, about {pct}% above a normal {day}.".format(
                    amt=today_str, pct=pct, day=weekday_name,
                )
            elif swing <= -_NOTABLE_SWING:
                pulse = "{amt} today, about {pct}% below a normal {day}.".format(
                    amt=today_str, pct=pct, day=weekday_name,
                )
            else:
                pulse = "{amt} today, right around a normal {day}.".format(
                    amt=today_str, day=weekday_name,
                )
        else:
            # Not enough same-weekday history to compare honestly: just the number.
            pulse = "{amt} rung up today so far.".format(amt=today_str)

        # Today's top seller (best-effort: a failure just drops the suffix).
        top_phrase = ""
        try:
            top = ctx.run_skill(
                "clover",
                "clover_lookup.py",
                ["--top-services", "--from", today_key, "--to", today_key,
                 "--limit", "1", "--json"],
            )
            if isinstance(top, list) and top and isinstance(top[0], dict):
                name = str(top[0].get("name") or "").strip()
                if name and name != "(unnamed)":
                    top_phrase = " Top seller: {}.".format(name)
        except Exception:
            top_phrase = ""

        summary = pulse + top_phrase

        return [
            Signal(
                # One pulse per day: stable entity_id keyed on the date so the
                # 20h cooldown plus dedup guarantees a single daily ping.
                entity_id="clover:sales_pulse:{}".format(today_key),
                amount=float(today_cents) / 100.0,
                summary=summary,
                proposal="",
                action=Action(kind=""),
                urgency="low",
            )
        ]
    except Exception:
        return []
