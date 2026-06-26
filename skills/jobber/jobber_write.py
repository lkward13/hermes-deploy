#!/usr/bin/env python3
"""
Jobber — writes (GraphQL mutations): create clients, quotes, jobs, requests, notes.

The write companion to jobber_lookup.py (reads). Reuses jobber_auth.py for OAuth
(auto-refresh) and the GraphQL transport.

Jobber is GraphQL only, so the primary tool is a raw mutation passthrough, with
convenience wrappers for the common create flows. The agent supplies the input
object as JSON; the wrapper builds the documented mutation and surfaces any
`userErrors` / top-level `errors`.

  mutation       — run any raw GraphQL mutation (universal escape hatch)
  create-client  — clientCreate(input: ...)
  create-quote   — quoteCreate(input: ...)
  create-job     — jobCreate(input: ...)
  create-request — requestCreate(input: ...)
  note           — attach a note to a Client/Job/Quote/etc. (noteCreate)

Examples:
  python3 jobber_write.py create-client '{"firstName":"Jane","lastName":"Doe","emails":[{"address":"jane@x.com","primary":true}]}'
  python3 jobber_write.py create-quote '{"clientId":"Z2lk...","lineItems":[{"name":"Roof repair","quantity":1,"unitPrice":1200}]}'
  python3 jobber_write.py create-job '{"clientId":"Z2lk...","title":"Spring cleanup"}'
  python3 jobber_write.py create-request '{"clientId":"Z2lk...","title":"New lead from website"}'
  python3 jobber_write.py note Client Z2lk... "Called, left voicemail"
  python3 jobber_write.py mutation 'mutation($input:ClientCreateInput!){ clientCreate(input:$input){ client{ id } userErrors{ message } } }' --vars '{"input":{...}}'

Read first with jobber_lookup.py to find ids (e.g. `jobber_lookup.py clients --search Jane`).
If a documented field name is rejected, run `jobber_lookup.py introspect <InputType>`
to discover the live input shape, then use the raw `mutation` passthrough.

Credentials come from env (JOBBER_*) — see jobber_auth.py. No username/password.
"""

import argparse
import json
import sys

import requests

from jobber_auth import run_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(raw: str, what: str = "input") -> dict:
    if raw == "-":
        raw = sys.stdin.read()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {what} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj, dict):
        print(f"error: {what} must be a JSON object", file=sys.stderr)
        sys.exit(1)
    return obj


def _run(query: str, variables: dict, as_json: bool, result_key: str, node_key: str, verb: str) -> None:
    """Execute a mutation, surface errors/userErrors, print a short result line."""
    payload = run_query(query, variables)

    # Top-level GraphQL errors (schema/validation/auth) abort.
    if payload.get("errors") and not payload.get("data"):
        msgs = "; ".join(e.get("message", str(e)) for e in payload["errors"])
        print(f"error: Jobber GraphQL: {msgs}", file=sys.stderr)
        sys.exit(1)

    data = payload.get("data") or {}
    result = data.get(result_key) or {}

    # Mutation-level userErrors (business validation).
    user_errors = result.get("userErrors") or []
    if user_errors:
        for ue in user_errors:
            path = ".".join(str(p) for p in (ue.get("path") or []))
            loc = f" [{path}]" if path else ""
            print(f"userError{loc}: {ue.get('message', ue)}", file=sys.stderr)
        # If nothing was created, treat as failure.
        if not result.get(node_key):
            sys.exit(1)

    node = result.get(node_key)
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    if node:
        nid = node.get("id", "?")
        name_val = node.get("name")
        if isinstance(name_val, dict):
            name_str = name_val.get("full", "")
        else:
            name_str = name_val or ""
        label = node.get("title") or name_str or ""
        for k in ("quoteNumber", "jobNumber", "invoiceNumber"):
            if node.get(k):
                label = f"#{node[k]} {label}".strip()
        print(f"{verb} {node_key} {nid}" + (f"  {label}" if label else ""))
    else:
        print(f"{verb} OK (no node returned)")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_mutation(args) -> None:
    variables = None
    if args.vars:
        variables = _parse_json(args.vars, "--vars")
    payload = run_query(args.mutation, variables)
    print(json.dumps(payload, indent=2))
    if payload.get("errors") and not payload.get("data"):
        sys.exit(1)


def cmd_create_client(args) -> None:
    inp = _parse_json(args.input)
    query = """
    mutation CreateClient($input: ClientCreateInput!) {
      clientCreate(input: $input) {
        client { id name { full firstName lastName } companyName }
        userErrors { message path }
      }
    }
    """
    _run(query, {"input": inp}, args.json, "clientCreate", "client", "Created")


def cmd_create_quote(args) -> None:
    inp = _parse_json(args.input)
    query = """
    mutation CreateQuote($input: QuoteCreateInput!) {
      quoteCreate(input: $input) {
        quote { id quoteNumber title quoteStatus total }
        userErrors { message path }
      }
    }
    """
    _run(query, {"input": inp}, args.json, "quoteCreate", "quote", "Created")


def cmd_create_job(args) -> None:
    inp = _parse_json(args.input)
    query = """
    mutation CreateJob($input: JobCreateInput!) {
      jobCreate(input: $input) {
        job { id jobNumber title jobStatus }
        userErrors { message path }
      }
    }
    """
    _run(query, {"input": inp}, args.json, "jobCreate", "job", "Created")


def cmd_create_request(args) -> None:
    inp = _parse_json(args.input)
    query = """
    mutation CreateRequest($input: RequestCreateInput!) {
      requestCreate(input: $input) {
        request { id title requestStatus }
        userErrors { message path }
      }
    }
    """
    _run(query, {"input": inp}, args.json, "requestCreate", "request", "Created")


def cmd_note(args) -> None:
    # Jobber attaches notes via noteCreate with the target object's id.
    # Field/input names vary; if rejected, introspect NoteCreateInput and use
    # the raw `mutation` passthrough.
    query = """
    mutation CreateNote($input: NoteCreateInput!) {
      noteCreate(input: $input) {
        note { id message }
        userErrors { message path }
      }
    }
    """
    inp = {"linkedToId": args.id, "message": args.text}
    _run(query, {"input": inp}, args.json, "noteCreate", "note", "Added")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Jobber — writes (GraphQL mutations)")
    p.add_argument("--json", action="store_true", help="print the full GraphQL response envelope")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mutation", help="run any raw GraphQL mutation (escape hatch)")
    m.add_argument("mutation", help="GraphQL mutation string")
    m.add_argument("--vars", help="JSON object of GraphQL variables (or '-' for stdin)")

    cc = sub.add_parser("create-client", help="clientCreate(input: <json>)")
    cc.add_argument("input", help="JSON input object (or '-' to read stdin)")

    cq = sub.add_parser("create-quote", help="quoteCreate(input: <json>)")
    cq.add_argument("input", help="JSON input object (or '-' to read stdin)")

    cj = sub.add_parser("create-job", help="jobCreate(input: <json>)")
    cj.add_argument("input", help="JSON input object (or '-' to read stdin)")

    cr = sub.add_parser("create-request", help="requestCreate(input: <json>) — create a lead")
    cr.add_argument("input", help="JSON input object (or '-' to read stdin)")

    nt = sub.add_parser("note", help="attach a note to an object (noteCreate)")
    nt.add_argument("type", help="object type, e.g. Client / Job / Quote (documentation only)")
    nt.add_argument("id", help="the object's GraphQL id")
    nt.add_argument("text", help="note text")

    args = p.parse_args()

    handlers = {
        "mutation": cmd_mutation,
        "create-client": cmd_create_client,
        "create-quote": cmd_create_quote,
        "create-job": cmd_create_job,
        "create-request": cmd_create_request,
        "note": cmd_note,
    }
    try:
        handlers[args.cmd](args)
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
