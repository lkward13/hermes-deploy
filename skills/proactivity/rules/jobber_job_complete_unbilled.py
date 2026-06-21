"""Proactivity rule: Jobber jobs finished but never invoiced (money sitting).

The classic leak for a service business: the crew finishes the work, marks the
job done in Jobber, and nobody ever cuts the invoice. The revenue is fully
earned, just sitting there uncollected. This rule catches "you finished X,
never billed, ~$Y sitting" and offers a one-tap draft invoice.

Read-only by contract: it only runs jobber_lookup.py (queries, never mutations)
via ctx.run_skill, never touches the Jobber write path itself. The actual draft
is the engine's job when the owner taps (action kind jobber.draft_invoice).

House rule: zero em dashes anywhere. Pure stdlib.
"""

from __future__ import annotations

from hermes_cli.nodesk_proactivity import RuleSpec, Signal, Action


RULE = RuleSpec(
    key="jobber.job_complete_unbilled",
    title="Finished job never invoiced",
    providers=("jobber",),
    category="collect_now",
    cadence_minutes=240,
    default_autonomy="draft",
    cooldown_hours=168.0,
    materiality={"min_amount": 250.0},
)

# Jobber jobStatus values that mean the work is done (so it should have been
# billed by now). We keep this generous and match case-insensitively so a schema
# label drift (e.g. "complete" vs "completed") does not silently mute the rule.
_DONE_STATUSES = ("complete", "completed", "archived", "closed")

# A raw GraphQL query is the robust path: the convenience `jobs` listing does
# not expose invoice linkage, so we ask for it directly (invoices.totalCount).
# If a field name drifts and Jobber rejects it, we fall back to the convenience
# listing below (which cannot prove billed/unbilled, so we stay conservative).
_RAW_QUERY = (
    "query($first:Int!){ jobs(first:$first){ edges { node { "
    "id jobNumber title jobStatus total "
    "client { id name { full } } "
    "invoices { totalCount } "
    "} } } }"
)

_PAGE = 50


def _money(node):
    """Pull a numeric dollar amount off a job node, tolerating shapes."""
    val = node.get("total")
    if isinstance(val, dict):
        # Some Jobber money fields nest as {"amount": ...} / {"value": ...}.
        val = val.get("amount", val.get("value"))
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _is_done(node):
    status = node.get("jobStatus")
    if not isinstance(status, str):
        return False
    s = status.strip().lower()
    return any(tok in s for tok in _DONE_STATUSES)


def _is_unbilled(node):
    """True only when we can affirmatively see zero invoices on the job. If the
    invoice field is missing (schema drift / fallback path) we return False so we
    never nag about a job that may already be billed."""
    inv = node.get("invoices")
    if not isinstance(inv, dict):
        return False
    count = inv.get("totalCount")
    try:
        return int(count) == 0
    except (TypeError, ValueError):
        return False


def _client_name(node):
    client = node.get("client") or {}
    name = client.get("name") or {}
    if isinstance(name, dict):
        full = name.get("full")
        if isinstance(full, str) and full.strip():
            return full.strip()
    return "a client"


def _job_label(node):
    title = node.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    num = node.get("jobNumber")
    if num is not None:
        return f"job #{num}"
    return "a job"


def _fmt_amount(amount):
    # Whole-dollar when clean, else two decimals. No em dashes anywhere.
    if amount == int(amount):
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _nodes_from_raw(payload):
    """Extract job nodes from the raw `query` subcommand payload
    ({"data": {"jobs": {"edges": [{"node": {...}}]}}})."""
    if not isinstance(payload, dict):
        return []
    if payload.get("errors") and not payload.get("data"):
        return []
    data = payload.get("data") or {}
    jobs = data.get("jobs") or {}
    edges = jobs.get("edges") or []
    out = []
    for e in edges:
        if isinstance(e, dict) and isinstance(e.get("node"), dict):
            out.append(e["node"])
    return out


def evaluate(ctx):
    try:
        payload = ctx.run_skill(
            "jobber",
            "jobber_lookup.py",
            ["query", _RAW_QUERY, "--vars", '{"first": %d}' % _PAGE],
        )
        nodes = _nodes_from_raw(payload)
        if not nodes:
            return []

        signals = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if not _is_done(node):
                continue
            if not _is_unbilled(node):
                continue
            amount = _money(node)
            if amount <= 0.0:
                continue

            job_id = node.get("id")
            if not job_id:
                continue

            who = _client_name(node)
            what = _job_label(node)
            money = _fmt_amount(amount)

            summary = (
                f"You finished \"{what}\" for {who} but never billed it. "
                f"{money} is just sitting there."
            )
            proposal = "Draft the invoice so you can send it?"

            signals.append(
                Signal(
                    entity_id=f"job:{job_id}",
                    summary=summary,
                    proposal=proposal,
                    action=Action(
                        kind="jobber.draft_invoice",
                        params={
                            "job_id": str(job_id),
                            "client_name": who,
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
