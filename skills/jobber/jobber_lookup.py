#!/usr/bin/env python3
"""
Jobber — read-only lookups, raw GraphQL queries, and schema introspection.

The broad "read everything" companion to jobber_write.py (mutations). Reuses
jobber_auth.py for OAuth (auto-refresh) and the GraphQL transport. Read-only:
runs queries only (never mutations).

Jobber is GraphQL only, so beyond convenience commands there are two escape
hatches that make this skill robust even if a built-in field name drifts:

  query      — run any raw GraphQL query (the universal escape hatch)
  introspect — discover the LIVE schema (root fields, or one type's fields)

Convenience connection queries (shallow + paginated):
  account, clients, requests (leads), quotes, jobs, invoices, visits/schedule,
  payments, and `get <Type> <id>`.

Examples:
  python3 jobber_lookup.py account
  python3 jobber_lookup.py clients --search "Smith" --limit 20
  python3 jobber_lookup.py requests --limit 10            # leads
  python3 jobber_lookup.py quotes --limit 20
  python3 jobber_lookup.py invoices --limit 20            # who owes me
  python3 jobber_lookup.py schedule --today               # today's visits
  python3 jobber_lookup.py get Client Z2lkOi8v...
  python3 jobber_lookup.py introspect                     # list root query fields
  python3 jobber_lookup.py introspect Client              # list Client's fields
  python3 jobber_lookup.py query 'query { account { id name } }'
  python3 jobber_lookup.py query 'query($id:ID!){ client(id:$id){ name } }' --vars '{"id":"..."}'

Add --json to any command for raw JSON output.

Credentials come from env (JOBBER_*) — see jobber_auth.py. No username/password.
"""

import argparse
import datetime
import json
import sys

import requests

from jobber_auth import run_query, graphql_version

# Cap on `first` for any connection query (keeps cost + throttle in check).
MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------

def _exec(query: str, variables: dict | None = None) -> dict:
    """Run a query and surface any GraphQL errors (exit 1 on hard errors)."""
    payload = run_query(query, variables)
    errors = payload.get("errors")
    if errors:
        msgs = "; ".join(e.get("message", str(e)) for e in errors)
        # Some GraphQL errors are partial (data still present). Only abort if
        # there's no usable data at all.
        if not payload.get("data"):
            print(f"error: Jobber GraphQL: {msgs}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"warning: Jobber GraphQL (partial): {msgs}", file=sys.stderr)
    return payload.get("data") or {}


def _clamp(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


def _print(obj, as_json: bool, human_fn=None) -> None:
    if as_json or human_fn is None:
        print(json.dumps(obj, indent=2))
        return
    human_fn(obj)


def _edges(conn: dict) -> list:
    return [e.get("node", {}) for e in (conn or {}).get("edges", [])]


def _page_note(conn: dict) -> str:
    info = (conn or {}).get("pageInfo", {})
    if info.get("hasNextPage"):
        return f"  (more available — endCursor={info.get('endCursor')})"
    return ""


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_account(args) -> None:
    data = _exec("query { account { id name } }")
    acct = data.get("account") or {}

    def human(_):
        if not acct:
            print("Connected, but no account returned.")
            return
        print(f"Account : {acct.get('name', '')}")
        print(f"ID      : {acct.get('id', '')}")
        print(f"Schema  : X-JOBBER-GRAPHQL-VERSION = {graphql_version()}")
        print("Status  : connected OK")

    _print(acct, args.json, human)


def cmd_query(args) -> None:
    variables = _parse_vars(args.vars)
    payload = run_query(args.query, variables)
    # Raw passthrough: print the whole envelope (data + errors + extensions).
    print(json.dumps(payload, indent=2))
    if payload.get("errors") and not payload.get("data"):
        sys.exit(1)


def cmd_introspect(args) -> None:
    if args.type_name:
        q = """
        query IntrospectType($name: String!) {
          __type(name: $name) {
            name
            kind
            description
            fields(includeDeprecated: true) {
              name
              description
              type { name kind ofType { name kind ofType { name kind } } }
            }
            inputFields {
              name
              type { name kind ofType { name kind ofType { name kind } } }
            }
          }
        }
        """
        data = _exec(q, {"name": args.type_name})
        t = data.get("__type")
        if not t:
            print(f"No type named '{args.type_name}' in schema version {graphql_version()}.")
            return

        def human(_):
            print(f"type {t.get('name')} ({t.get('kind')})")
            if t.get("description"):
                print(f"  {t['description']}")
            fields = t.get("fields") or t.get("inputFields") or []
            label = "fields" if t.get("fields") else "inputFields"
            print(f"  {label}:")
            for f in fields:
                print(f"    {f.get('name')}: {_typestr(f.get('type'))}")

        _print(t, args.json, human)
        return

    # No type given: list the root query + mutation field names.
    q = """
    query IntrospectRoots {
      __schema {
        queryType { name fields { name } }
        mutationType { name fields { name } }
      }
    }
    """
    data = _exec(q)
    schema = data.get("__schema", {})

    def human(_):
        qt = schema.get("queryType") or {}
        mt = schema.get("mutationType") or {}
        print(f"Schema version: {graphql_version()}")
        print(f"\nQuery root ({qt.get('name', 'Query')}):")
        for f in qt.get("fields", []):
            print(f"  {f.get('name')}")
        print(f"\nMutation root ({mt.get('name', 'Mutation')}):")
        for f in (mt.get("fields") or []):
            print(f"  {f.get('name')}")
        print("\nTip: `introspect <TypeName>` lists a type's fields.")

    _print(schema, args.json, human)


def _typestr(t: dict | None) -> str:
    """Flatten a GraphQL type ref (handling NON_NULL/LIST wrappers) to a string."""
    if not t:
        return "?"
    kind = t.get("kind")
    name = t.get("name")
    of = t.get("ofType")
    if kind == "NON_NULL":
        return _typestr(of) + "!"
    if kind == "LIST":
        return "[" + _typestr(of) + "]"
    return name or (_typestr(of) if of else "?")


# --- connection queries ----------------------------------------------------

def _connection(field: str, node_fields: str, args, filter_args: str = "", filter_block: str = "") -> None:
    """Generic shallow connection query: <field>(first: N) { edges { node {...} } }."""
    first = _clamp(args.limit)
    after = f', after: "{args.after}"' if getattr(args, "after", None) else ""
    arg_str = f"first: {first}{after}{filter_args}"
    query = f"""
    query {{
      {field}({arg_str}) {{
        edges {{ node {{ {node_fields} }} }}
        pageInfo {{ hasNextPage endCursor }}
        totalCount
      }}
    }}
    """
    data = _exec(query)
    conn = data.get(field, {})
    nodes = _edges(conn)

    def human(_):
        if not nodes:
            print(f"No {field} found.")
            return
        for n in nodes:
            print("- " + _summarize(field, n))
        total = conn.get("totalCount")
        suffix = f" of {total}" if total is not None else ""
        print(f"({len(nodes)} shown{suffix}){_page_note(conn)}")

    _print(nodes, args.json, human)


def _name_of(node: dict) -> str:
    n = node.get("name")
    if isinstance(n, dict):
        # client name is often a structured Name { full firstName lastName }
        return n.get("full") or " ".join(
            filter(None, [n.get("firstName"), n.get("lastName")])
        )
    if isinstance(n, str):
        return n
    # client {} convenience joins
    c = node.get("client") or {}
    cn = c.get("name")
    if isinstance(cn, dict):
        return cn.get("full") or ""
    return cn or ""


def _summarize(field: str, n: dict) -> str:
    nid = n.get("id", "")
    title = n.get("title") or _name_of(n) or n.get("subject") or ""
    bits = [nid[:24]]
    if title:
        bits.append(title[:34])
    # Field-specific extras.
    for k in ("quoteNumber", "jobNumber", "invoiceNumber"):
        if n.get(k):
            bits.append(f"#{n[k]}")
    if n.get("total") is not None:
        bits.append(_money(n["total"]))
    if n.get("invoiceBalance") is not None:
        bits.append(f"bal {_money(n['invoiceBalance'])}")
    for k in ("startAt", "createdAt", "issuedDate", "dueDate"):
        if n.get(k):
            bits.append(str(n[k]))
            break
    if n.get("invoiceStatus"):
        bits.append(str(n["invoiceStatus"]))
    if n.get("quoteStatus"):
        bits.append(str(n["quoteStatus"]))
    if n.get("jobStatus"):
        bits.append(str(n["jobStatus"]))
    return "  ".join(b for b in bits if b)


def _money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def cmd_clients(args) -> None:
    filt = ""
    if args.search:
        # Jobber clients connection supports a `searchTerm` filter argument.
        safe = args.search.replace('"', '\\"')
        filt = f', searchTerm: "{safe}"'
    _connection(
        "clients",
        "id name { full firstName lastName } "
        "emails { description address primary } "
        "phones { description number primary } "
        "isCompany companyName",
        args,
        filter_args=filt,
    )


def cmd_requests(args) -> None:
    _connection(
        "requests",
        "id title createdAt requestStatus "
        "client { id name { full } } "
        "property { id address { street city province postalCode } }",
        args,
    )


def cmd_quotes(args) -> None:
    _connection(
        "quotes",
        "id quoteNumber title quoteStatus total createdAt "
        "client { id name { full } }",
        args,
    )


def cmd_jobs(args) -> None:
    _connection(
        "jobs",
        "id jobNumber title jobStatus total createdAt "
        "client { id name { full } }",
        args,
    )


def cmd_invoices(args) -> None:
    _connection(
        "invoices",
        "id invoiceNumber subject invoiceStatus total invoiceBalance "
        "issuedDate dueDate client { id name { full } }",
        args,
    )


def cmd_visits(args) -> None:
    filt = ""
    if getattr(args, "today", False):
        today = datetime.date.today()
        start = f"{today.isoformat()}T00:00:00Z"
        end = f"{today.isoformat()}T23:59:59Z"
        # `filter` on the visits connection narrows by start time window.
        filt = (
            f', filter: {{ startAt: {{ after: "{start}", before: "{end}" }} }}'
        )
    _connection(
        "visits",
        "id title startAt endAt completedAt "
        "job { id jobNumber } client { id name { full } }",
        args,
        filter_args=filt,
    )


def cmd_payments(args) -> None:
    _connection(
        "invoicePayments",
        "id amount paymentType entryDate "
        "client { id name { full } } invoice { id invoiceNumber }",
        args,
    )


def cmd_get(args) -> None:
    # Map a Type name to its singular root query field (lowercased first letter).
    type_name = args.type
    root = type_name[0].lower() + type_name[1:]
    # Generic single-node fetch with a small common field set. For exotic types,
    # use `query`/`introspect` to craft a precise selection.
    query = f"""
    query GetNode($id: ID!) {{
      {root}(id: $id) {{
        id
        ... on {type_name} {{
          __typename
        }}
      }}
    }}
    """
    # The minimal selection above is robust but thin; prefer the explicit
    # per-type selection when we know the type.
    selections = {
        "Client": "id name { full firstName lastName } emails { address primary } phones { number primary } isCompany companyName",
        "Request": "id title requestStatus createdAt client { name { full } } property { address { street city province postalCode } }",
        "Quote": "id quoteNumber title quoteStatus total createdAt client { name { full } }",
        "Job": "id jobNumber title jobStatus total createdAt client { name { full } }",
        "Invoice": "id invoiceNumber subject invoiceStatus total invoiceBalance issuedDate dueDate client { name { full } }",
        "Visit": "id title startAt endAt completedAt job { jobNumber } client { name { full } }",
        "Property": "id address { street city province postalCode } client { name { full } }",
    }
    sel = selections.get(type_name, "id")
    query = f"""
    query GetNode($id: ID!) {{
      {root}(id: $id) {{ {sel} }}
    }}
    """
    data = _exec(query, {"id": args.id})
    node = data.get(root)
    if node is None:
        print(f"No {type_name} with id {args.id} (or wrong root field '{root}').")
        return
    print(json.dumps(node, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_vars(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: --vars is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(v, dict):
        print("error: --vars must be a JSON object", file=sys.stderr)
        sys.exit(1)
    return v


def _add_limit(parser) -> None:
    parser.add_argument("--limit", type=int, default=25, help=f"max rows (maps to GraphQL `first`, cap {MAX_LIMIT})")
    parser.add_argument("--after", help="pagination cursor (pageInfo.endCursor from a previous page)")


def main() -> int:
    p = argparse.ArgumentParser(description="Jobber — read-only lookups, raw GraphQL, schema introspection")
    p.add_argument("--json", action="store_true", help="raw JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("account", help="connectivity + token check (account { id name })")

    q = sub.add_parser("query", help="run any raw GraphQL query (escape hatch)")
    q.add_argument("query", help="GraphQL query string")
    q.add_argument("--vars", help="JSON object of GraphQL variables")

    ins = sub.add_parser("introspect", help="discover the live schema (no arg: roots; with Type: its fields)")
    ins.add_argument("type_name", nargs="?", help="optional GraphQL type name, e.g. Client")

    cl = sub.add_parser("clients", help="list clients")
    cl.add_argument("--search", help="fuzzy name/company search term")
    _add_limit(cl)

    rq = sub.add_parser("requests", help="list requests (leads)")
    _add_limit(rq)

    qu = sub.add_parser("quotes", help="list quotes")
    _add_limit(qu)

    jb = sub.add_parser("jobs", help="list jobs")
    _add_limit(jb)

    inv = sub.add_parser("invoices", help="list invoices (use to see who owes you)")
    _add_limit(inv)

    vi = sub.add_parser("visits", help="list visits (scheduling)")
    vi.add_argument("--today", action="store_true", help="only today's visits")
    _add_limit(vi)

    sc = sub.add_parser("schedule", help="alias for visits (use --today for today's schedule)")
    sc.add_argument("--today", action="store_true", help="only today's visits")
    _add_limit(sc)

    pay = sub.add_parser("payments", help="list invoice payments")
    _add_limit(pay)

    g = sub.add_parser("get", help="fetch a single node by id")
    g.add_argument("type", help="GraphQL type, e.g. Client / Quote / Job / Invoice / Visit")
    g.add_argument("id", help="the node's GraphQL id")

    args = p.parse_args()

    handlers = {
        "account": cmd_account,
        "query": cmd_query,
        "introspect": cmd_introspect,
        "clients": cmd_clients,
        "requests": cmd_requests,
        "quotes": cmd_quotes,
        "jobs": cmd_jobs,
        "invoices": cmd_invoices,
        "visits": cmd_visits,
        "schedule": cmd_visits,  # schedule is visits with --today
        "payments": cmd_payments,
        "get": cmd_get,
    }
    try:
        handlers[args.cmd](args)
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
