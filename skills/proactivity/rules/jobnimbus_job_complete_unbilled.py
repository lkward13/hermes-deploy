"""Proactivity rule: JobNimbus jobs finished but never invoiced (money sitting).

The classic contractor leak: the crew wraps the roof, marks the job complete in
JobNimbus, and nobody ever cuts the invoice. The revenue is fully earned, just
sitting there uncollected. This rule catches "you finished X for Y, never billed,
~$Z sitting" and offers a one-tap draft invoice.

Read-only by contract: it only runs jobnimbus_lookup.py (GET-only lookups, never
mutations) via ctx.run_skill, never touches any write path. The actual draft is
the engine's job when the owner taps (action kind jobnimbus.draft_invoice).

Proof model (so we never nag about an already-billed job):
  done jobs  = jobs whose status_name reads as complete/closed/won
  billed set = every job jnid we can see referenced by any invoice
  unbilled   = done jobs NOT in the billed set, with a positive dollar amount
If we cannot read the invoice list at all (skill missing / key dead / rate
limit -> run_skill returns None), we emit nothing rather than guess.

There may be no jobnimbus skill dir on a given box yet. ctx.run_skill returns
None when the script is absent, so this rule degrades to silence safely. The
engine's provider gate already skips it unless "jobnimbus" is connected.

House rule: zero em dashes anywhere. Pure stdlib.
"""

from __future__ import annotations

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="jobnimbus.job_complete_unbilled",
    title="Finished JobNimbus job never invoiced",
    providers=("jobnimbus",),
    category="collect_now",
    cadence_minutes=240,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={"min_amount": 250.0},
)

# JobNimbus status_name values that mean the field work is done (so it should
# have been billed by now). Matched case-insensitively as substrings so a label
# drift on the customer's board ("Job Complete" vs "Completed" vs "Job Closed")
# does not silently mute the rule.
_DONE_STATUSES = ("complete", "completed", "closed", "won", "paid", "finished")

# Status labels that mean the work is NOT actually done, guarded against the
# substring match above accidentally firing (e.g. "Not Complete", "Lost").
_NOT_DONE = ("not complete", "incomplete", "lost", "cancel", "void", "dead")

_JOB_PAGE = 100
_INVOICE_PAGE = 200


def _as_rows(payload):
    """jobnimbus_lookup.py --json prints the bare results list. Tolerate both the
    bare list and the raw {count, results:[...]} wrapper just in case."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        rows = payload.get("results")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _money(node):
    """Pull a numeric dollar amount off a job node, tolerating JobNimbus field
    shapes. Returns 0.0 when nothing usable is present."""
    for key in ("total", "approved_estimate_total", "estimate_total",
                "job_value", "value", "amount"):
        val = node.get(key)
        if isinstance(val, dict):
            val = val.get("amount", val.get("value"))
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        if num > 0.0:
            return num
    return 0.0


def _status_text(node):
    status = node.get("status_name")
    if not isinstance(status, str):
        return ""
    return status.strip().lower()


def _is_done(node):
    s = _status_text(node)
    if not s:
        return False
    if any(tok in s for tok in _NOT_DONE):
        return False
    return any(tok in s for tok in _DONE_STATUSES)


def _job_label(node):
    for key in ("name", "display_name"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    num = node.get("number")
    if num not in (None, ""):
        return f"job #{num}"
    return "a job"


def _customer_name(node):
    for key in ("primary_contact_name", "contact_name", "display_name",
                "sales_rep_name"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "a customer"


def _fmt_amount(amount):
    # Whole-dollar when clean, else two decimals. No em dashes anywhere.
    if amount == int(amount):
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _collect_ids(obj, out):
    """Walk an arbitrary invoice record and collect every jnid/id string it
    references. JobNimbus links an invoice to its job through a `related` array
    (entries carry the job's jnid), but field naming varies, so we scan the whole
    record defensively: any job jnid that shows up anywhere in an invoice means
    that job is billed."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("jnid", "id", "related_id", "parent_id") and isinstance(v, str) and v:
                out.add(v)
            else:
                _collect_ids(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_ids(item, out)


def _billed_job_ids(invoices):
    """The set of job jnids referenced by any invoice."""
    billed = set()
    for inv in invoices:
        _collect_ids(inv, billed)
    return billed


def evaluate(ctx):
    try:
        # 1) Done jobs. Filter server-side to the common done status when we can,
        # but the rule re-checks status locally so a filter miss is harmless.
        jobs_payload = ctx.run_skill(
            "jobnimbus",
            "jobnimbus_lookup.py",
            ["--list-jobs", "--json", "--limit", str(_JOB_PAGE)],
        )
        jobs = _as_rows(jobs_payload)
        if not jobs:
            return []

        done_jobs = [j for j in jobs if _is_done(j) and j.get("jnid")]
        if not done_jobs:
            return []

        # 2) Invoices. If we cannot read them at all, stay silent (never nag
        # about a job that may already be billed). An empty-but-readable list is
        # a real signal: nothing billed yet.
        invoices_payload = ctx.run_skill(
            "jobnimbus",
            "jobnimbus_lookup.py",
            ["--list-invoices", "--json", "--limit", str(_INVOICE_PAGE)],
        )
        if invoices_payload is None:
            return []
        invoices = _as_rows(invoices_payload)
        billed = _billed_job_ids(invoices)

        signals = []
        for job in done_jobs:
            jnid = job.get("jnid")
            if not isinstance(jnid, str) or not jnid:
                continue
            if jnid in billed:
                continue
            amount = _money(job)
            if amount <= 0.0:
                # No provable dollar amount means we cannot rank or pass
                # materiality honestly, so skip rather than invent a number.
                continue

            who = _customer_name(job)
            what = _job_label(job)
            money = _fmt_amount(amount)

            summary = (
                f"You finished \"{what}\" for {who} but never invoiced it. "
                f"{money} is just sitting there in JobNimbus."
            )
            proposal = "Draft the invoice so you can send it?"

            signals.append(
                Signal(
                    entity_id=f"job:{jnid}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="jobnimbus.draft_invoice",
                        params={
                            "job_id": jnid,
                            "customer_name": who,
                            "amount": amount,
                        },
                    ),
                    amount=amount,
                    count=1,
                    urgency="normal",
                )
            )
        return signals
    except Exception:
        return []
