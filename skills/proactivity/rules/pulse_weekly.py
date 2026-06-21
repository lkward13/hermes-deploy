"""Proactivity rule: pulse.weekly.

The Monday-morning business pulse. Once a week, roll up what the money tools say
about the last 7 days versus the 7 before it and hand the owner one punchy line:
revenue, collections, and new customers, with the week-over-week swing named in
plain English ("$8,400 in, up 22% from last week"). Informational only: no action,
no proposal, no token writes. It is the "you are not flying blind" ping.

Providers: qbo, jobber, clover. The engine fires this rule when ANY of those is
connected; inside evaluate() we pull whatever is cheaply available from each
connected provider via ctx.run_skill (read-only lookup scripts only) and merge
the numbers into a single weekly Signal. One provider being down or quiet never
sinks the pulse, it just drops that provider's slice.

What each provider contributes, all via one or two cheap read-only calls:

  QBO  (qbo-invoicing/qbo_lookup.py)
    - revenue:     sum of Invoice TotalAmt with TxnDate in the window
        list Invoice --where "TxnDate >= 'D'" --json  -> [{TotalAmt, TxnDate, ...}]
    - collections: sum of Payment TotalAmt with TxnDate in the window
        list Payment --where "TxnDate >= 'D'" --json  -> [{TotalAmt, TxnDate, ...}]
    - new customers (a clean proxy for new leads for an accounting shop):
        list Customer --where "Metadata.CreateTime >= 'D'" --json (best-effort)

  Jobber (jobber/jobber_lookup.py)
    - billed: sum of invoice total for invoices issued in the window
        invoices --json -> [{total, issuedDate, ...}]

  Clover (clover/clover_lookup.py)
    - revenue: sum of non-voided payment amounts (cents) in the window
        --sales-summary --from D --to D --json
          -> [{amount(cents), result, createdTime(epoch ms)}]

All numbers the owner sees are real and summed from the raw rows, never guessed.
If a number cannot be computed honestly we drop it rather than fake it.

House rule: zero em dashes (the long horizontal dash) anywhere. Periods, commas,
colons, parens only. Pure stdlib.
"""

from __future__ import annotations

import datetime

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="pulse.weekly",
    title="Weekly business pulse",
    providers=("qbo", "jobber", "clover"),
    category="pulse",
    cadence_minutes=1440,                  # evaluate once a day
    default_autonomy="draft",
    cooldown_hours=144.0,                   # but fire at most once every ~6 days
    materiality={},                         # informational: no floors
)

# A "week" is the trailing 7 days; "last week" is the 7 before that. Comparing
# trailing windows (not calendar weeks) means the pulse reads the same no matter
# which day the tick lands on.
_WINDOW_DAYS = 7

# Voided / refunded Clover results to exclude from revenue (mirrors the skill).
_VOID_RESULTS = ("VOIDED", "VOID")

# Only call out an up/down swing when it clears this fraction, so ordinary
# week-to-week noise does not get dressed up as a trend.
_NOTABLE_SWING = 0.10


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _money(v: float) -> str:
    """$8,400 when whole, $8,400.50 otherwise."""
    if v == int(v):
        return "${:,.0f}".format(v)
    return "${:,.2f}".format(v)


def _parse_date(s):
    """'YYYY-MM-DD' (QBO / Jobber dates) -> date, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _date_from_ms(ms):
    """Clover epoch-ms -> UTC date, or None (matches the skill's bucketing)."""
    try:
        val = int(ms)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.datetime.utcfromtimestamp(val / 1000.0).date()
    except (OverflowError, OSError, ValueError):
        return None


def _bucket(d, this_start, last_start):
    """Return 'this', 'last', or None for a date relative to the two windows."""
    if d is None:
        return None
    if d >= this_start:
        return "this"
    if d >= last_start:
        return "last"
    return None


def _swing_phrase(this_val, last_val):
    """Plain-English week-over-week direction, or '' when not worth saying."""
    if last_val <= 0:
        return ""
    swing = (this_val - last_val) / last_val
    pct = int(round(abs(swing) * 100))
    if swing >= _NOTABLE_SWING:
        return ", up {}% from last week".format(pct)
    if swing <= -_NOTABLE_SWING:
        return ", down {}% from last week".format(pct)
    return ", about flat with last week"


# ---------------------------------------------------------------------------
# Per-provider collectors. Each returns a dict of metric -> (this, last) dollar
# pairs (counts for new-customers), best-effort. A failure returns {} so the
# pulse still ships with the other providers' slices.
# ---------------------------------------------------------------------------

def _qbo_metrics(ctx, this_start, last_start):
    out = {}
    cutoff = last_start.isoformat()

    # Revenue: invoices dated in the two windows.
    try:
        invoices = ctx.run_skill(
            "qbo-invoicing", "qbo_lookup.py",
            ["--json", "list", "Invoice", "--where", "TxnDate >= '{}'".format(cutoff),
             "--limit", "1000"],
        )
        if isinstance(invoices, list):
            rev_this = rev_last = 0.0
            for r in invoices:
                if not isinstance(r, dict):
                    continue
                b = _bucket(_parse_date(r.get("TxnDate")), this_start, last_start)
                if b == "this":
                    rev_this += _to_float(r.get("TotalAmt"))
                elif b == "last":
                    rev_last += _to_float(r.get("TotalAmt"))
            out["revenue"] = (rev_this, rev_last)
    except Exception:
        pass

    # Collections: payments received in the two windows.
    try:
        payments = ctx.run_skill(
            "qbo-invoicing", "qbo_lookup.py",
            ["--json", "list", "Payment", "--where", "TxnDate >= '{}'".format(cutoff),
             "--limit", "1000"],
        )
        if isinstance(payments, list):
            col_this = col_last = 0.0
            for r in payments:
                if not isinstance(r, dict):
                    continue
                b = _bucket(_parse_date(r.get("TxnDate")), this_start, last_start)
                if b == "this":
                    col_this += _to_float(r.get("TotalAmt"))
                elif b == "last":
                    col_last += _to_float(r.get("TotalAmt"))
            out["collections"] = (col_this, col_last)
    except Exception:
        pass

    # New customers (a clean proxy for new leads on an accounting connection).
    try:
        customers = ctx.run_skill(
            "qbo-invoicing", "qbo_lookup.py",
            ["--json", "list", "Customer",
             "--where", "Metadata.CreateTime >= '{}'".format(cutoff),
             "--limit", "1000"],
        )
        if isinstance(customers, list):
            lead_this = lead_last = 0
            for r in customers:
                if not isinstance(r, dict):
                    continue
                created = (r.get("MetaData") or r.get("Metadata") or {}).get("CreateTime")
                b = _bucket(_parse_date(created), this_start, last_start)
                if b == "this":
                    lead_this += 1
                elif b == "last":
                    lead_last += 1
            out["leads"] = (lead_this, lead_last)
    except Exception:
        pass

    return out


def _jobber_metrics(ctx, this_start, last_start):
    out = {}
    try:
        rows = ctx.run_skill("jobber", "jobber_lookup.py", ["invoices", "--json"])
        if isinstance(rows, list):
            rev_this = rev_last = 0.0
            for inv in rows:
                if not isinstance(inv, dict):
                    continue
                b = _bucket(_parse_date(inv.get("issuedDate")), this_start, last_start)
                if b == "this":
                    rev_this += _to_float(inv.get("total"))
                elif b == "last":
                    rev_last += _to_float(inv.get("total"))
            out["revenue"] = (rev_this, rev_last)
    except Exception:
        pass
    return out


def _clover_metrics(ctx, this_start, last_start):
    out = {}
    # The fetch window spans both trailing weeks: from last_start through today
    # (today is this_start plus the trailing-window length minus one day). Using
    # this_start as the upper bound would drop the entire current week of sales.
    window_end = this_start + datetime.timedelta(days=_WINDOW_DAYS - 1)
    try:
        payments = ctx.run_skill(
            "clover", "clover_lookup.py",
            ["--sales-summary",
             "--from", last_start.isoformat(),
             "--to", window_end.isoformat(),  # skill --to is inclusive of today
             "--json"],
        )
        if isinstance(payments, list):
            rev_this = rev_last = 0
            for p in payments:
                if not isinstance(p, dict):
                    continue
                if str(p.get("result") or "").upper() in _VOID_RESULTS:
                    continue
                b = _bucket(_date_from_ms(p.get("createdTime")), this_start, last_start)
                try:
                    cents = int(p.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                if b == "this":
                    rev_this += cents
                elif b == "last":
                    rev_last += cents
            out["revenue"] = (rev_this / 100.0, rev_last / 100.0)
    except Exception:
        pass
    return out


def evaluate(ctx) -> list:
    try:
        now = ctx.now
        today = now.date() if isinstance(now, datetime.datetime) else datetime.date.today()
        this_start = today - datetime.timedelta(days=_WINDOW_DAYS - 1)
        last_start = this_start - datetime.timedelta(days=_WINDOW_DAYS)

        # Sum each metric across whichever providers reported it. Revenue from
        # QBO/Jobber/Clover all rolls into one top-line number, collections and
        # new-leads layer on where available.
        totals = {}   # metric -> [this, last]
        for collector in (_qbo_metrics, _jobber_metrics, _clover_metrics):
            try:
                metrics = collector(ctx, this_start, last_start)
            except Exception:
                continue
            if not isinstance(metrics, dict):
                continue
            for metric, pair in metrics.items():
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                acc = totals.setdefault(metric, [0.0, 0.0])
                acc[0] += pair[0]
                acc[1] += pair[1]

        if not totals:
            return []

        parts = []

        # Only speak to a metric with real activity THIS week. A cheerful weekly
        # pulse must never lead with "$0, down 100% from last week": a dead week
        # reads as something broken, not an insight. If nothing has current
        # activity the whole pulse is suppressed below (a deliberate "your
        # register went quiet" alert belongs in a separate, gentler rule).
        rev = totals.get("revenue")
        if rev is not None and rev[0] > 0:
            parts.append(
                "{}{} brought in".format(_money(rev[0]), _swing_phrase(rev[0], rev[1]))
            )

        col = totals.get("collections")
        if col is not None and col[0] > 0:
            parts.append(
                "{}{} collected".format(_money(col[0]), _swing_phrase(col[0], col[1]))
            )

        leads = totals.get("leads")
        if leads is not None and leads[0] > 0:
            n = int(round(leads[0]))
            noun = "new customer" if n == 1 else "new customers"
            parts.append("{} {}{}".format(n, noun, _swing_phrase(leads[0], leads[1])))

        if not parts:
            return []

        # Headline amount used for ranking: the top-line revenue if we have it,
        # else collections, else 0.
        head_amount = 0.0
        if rev is not None:
            head_amount = float(rev[0])
        elif col is not None:
            head_amount = float(col[0])

        # Join the slices into one Sam Parr line.
        if len(parts) == 1:
            body = parts[0] + "."
        elif len(parts) == 2:
            body = parts[0] + ", and " + parts[1] + "."
        else:
            body = ", ".join(parts[:-1]) + ", and " + parts[-1] + "."

        window_label = "{} to {}".format(
            this_start.strftime("%b %-d"), today.strftime("%b %-d"),
        )
        summary = "Weekly pulse ({}): {}".format(window_label, body)

        # Dedup key must be STABLE across the days of one week, or the daily
        # cadence would re-fire every day (a fresh trailing-window start date is a
        # brand new entity_id the cooldown has never seen). Key on the ISO
        # calendar week instead: it holds steady Monday through Sunday, so the
        # first tick of a new week fires and the 144h cooldown swallows the rest,
        # then the key rolls over next week. Exactly one ping per week.
        iso_year, iso_week, _ = today.isocalendar()
        return [
            Signal(
                entity_id="pulse:weekly:{:04d}-W{:02d}".format(iso_year, iso_week),
                amount=head_amount,
                count=int(round(leads[0])) if leads is not None else 0,
                summary=summary,
                proposal="",
                action=Action(kind=""),
                urgency="low",
            )
        ]
    except Exception:
        return []
