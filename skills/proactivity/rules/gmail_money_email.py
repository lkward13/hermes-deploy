"""Proactivity rule: gmail.money_email.

The triage rule that earns the inbox a seat at the table: NOT "you have N unread"
(noise the owner already feels guilty about), but a RESOLVED, one-at-a-time pull
of the emails that actually move money. A customer asking about an invoice, a
payment confirmation that needs a reply, a fresh job request landing in the inbox.
Each one becomes its own ping with the sender's name and what they want, plus a
one-tap "draft the reply" so the owner taps once instead of opening Gmail.

How it stays honest:
- We read only recent, unread, primary-category mail via google/gmail.py's
  read-only `list` command (a Gmail search query does the heavy lifting, so we
  pull a small set, never the whole inbox).
- We then CLASSIFY each candidate against money-intent keywords in the subject +
  snippet, so we surface a true, specific "this is about money" email, never a
  raw unread dump. An email that does not look like money is dropped silently.
- Each surfaced email is its own Signal with a STABLE entity_id ("gmail:<id>")
  so dedup fires the email exactly once per cooldown, no re-nagging on the same
  thread tick after tick.

Read-only by contract. The whole body is wrapped in try/except and returns [] on
any error (the engine isolates failures, but we stay safe anyway).

House rule: zero em dashes anywhere. Use periods, commas, colons, parens.
"""

from __future__ import annotations

import re


from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="gmail.money_email",
    title="Customer-money email",
    providers=("google",),
    category="triage",
    cadence_minutes=60,
    cooldown_hours=6.0,
    materiality={},
)


# The Gmail search that does the first cut: unread, recent, in the primary inbox
# (drop promotions/social/updates noise), and NOT something we already sent. We
# keep the pull small so this stays cheap.
_GMAIL_QUERY = (
    "is:unread newer_than:3d category:primary "
    "-from:me -in:chats -label:promotions -label:social"
)
_MAX_SCAN = 25


# Money-intent classifiers. Each tuple is (kind, label, [keywords]). Order is
# priority: an invoice/payment question outranks a generic new-job request when
# both match, so the summary names the most material thing.
_INTENTS = (
    (
        "invoice",
        "invoice question",
        (
            "invoice", "the bill", "your bill", "billing", "statement",
            "balance due", "amount due", "outstanding", "past due", "overdue",
            "remittance", "purchase order", "p.o.", "net 30", "net 15",
        ),
    ),
    (
        "payment",
        "payment",
        (
            "payment", "paid", "pay you", "paying", "deposit", "wire transfer",
            "wired", "ach", "check is", "check has", "card declined",
            "receipt", "refund", "chargeback", "venmo", "zelle",
        ),
    ),
    (
        "new_job",
        "new job request",
        (
            "quote", "estimate", "get a quote", "request a quote", "bid",
            "proposal", "new job", "new project", "looking for", "interested in",
            "do you do", "are you available", "availability", "book", "schedule",
            "how much", "pricing", "your rate", "rates", "cost to",
        ),
    ),
)


def _sender_name(raw: str) -> str:
    """Pull a clean display name out of a 'From' header. 'Jane Doe <j@x.com>'
    becomes 'Jane Doe'; a bare 'jane@x.com' becomes 'jane'."""
    s = (raw or "").strip()
    if not s:
        return "Someone"
    # Prefer the display-name half before the angle brackets.
    m = re.match(r'^\s*"?([^"<]+?)"?\s*<', s)
    if m:
        name = m.group(1).strip().strip('"').strip()
        if name:
            return name
    # No display name: derive a friendly handle from the address local-part.
    addr = s
    am = re.search(r"<([^>]+)>", s)
    if am:
        addr = am.group(1)
    local = addr.split("@", 1)[0].strip()
    local = re.sub(r"[._+-]+", " ", local).strip()
    return local.title() if local else "Someone"


def _classify(text: str):
    """Return (kind, label) for the first matching money intent, or None."""
    low = text.lower()
    for kind, label, words in _INTENTS:
        for w in words:
            if w in low:
                return kind, label
    return None


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def evaluate(ctx) -> list:
    try:
        rows = ctx.run_skill(
            "google",
            "gmail.py",
            ["list", "--max", str(_MAX_SCAN), "--query", _GMAIL_QUERY],
        )
        if not isinstance(rows, list):
            return []

        signals = []
        seen_ids = set()

        for r in rows:
            if not isinstance(r, dict):
                continue
            mid = str(r.get("id") or "").strip()
            if not mid or mid in seen_ids:
                continue

            subject = str(r.get("subject") or "").strip()
            snippet = str(r.get("snippet") or "").strip()
            from_raw = str(r.get("from") or "").strip()

            hit = _classify(f"{subject} {snippet}")
            if not hit:
                continue
            kind, label = hit

            seen_ids.add(mid)
            who = _sender_name(from_raw)
            subj = _clip(subject, 70) or "(no subject)"

            if kind == "invoice":
                summary = f'{who} emailed about an invoice: "{subj}".'
            elif kind == "payment":
                summary = f'{who} emailed about a payment: "{subj}".'
            else:
                summary = f'{who} wants to hire you: "{subj}".'

            signals.append(
                Signal(
                    entity_id=f"gmail:{mid}",
                    summary=summary,
                    proposal="Want me to draft a reply?",
                    action=Action(
                        kind="gmail.draft_reply",
                        params={
                            "message_id": mid,
                            "intent": kind,
                            "to": from_raw,
                            "subject": subject,
                        },
                    ),
                    amount=0.0,
                    count=1,
                    urgency="high" if kind in ("invoice", "payment") else "normal",
                )
            )

        return signals
    except Exception:
        return []
