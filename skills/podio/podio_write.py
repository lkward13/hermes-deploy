#!/usr/bin/env python3
"""
Write to Podio: create / update items, add comments, create / complete tasks.

This is the write companion to podio_lookup.py (reads). It reuses the exact
same OAuth auth and auto-refresh-on-401 helpers from podio_lookup.py, so there
is one place that knows about tokens.

Podio's data model: an app holds items; each item is a set of fields; items can
have comments, tasks, and files. Fields are addressed by their external_id (the
stable, human-readable slug, e.g. "title", "phone") or by their numeric
field_id. Field VALUES are type-specific shapes (see "Field shapes" below); this
tool coerces simple --field key=value pairs into the right shape for the common
types, or you can pass a raw --json field map for full control.

Subcommands:
  create-item   --app <id> --field title="Acme" --field phone=+14055551234 ...
  create-item   --app <id> --json '{"title":"Acme","status":"New Lead"}'
  update-item   <item_id> --field status="Quoted" ...
  update-item   <item_id> --json '{"status":"Quoted"}'
  comment       <item_id> "Called the customer, left a voicemail"
  task          "Follow up with Acme" --item <item_id> --due 2026-07-01
  complete-task <task_id>

Field value coercion (--field key=value):
  - text / number          : value passed through as a string/number
  - phone / email          : wrapped as [{"type":"other","value": value}]
  - category / status      : resolved to an option id (accepts the label OR id)
  - date                   : {"start": "YYYY-MM-DD"} (accepts "YYYY-MM-DD HH:MM:SS")
  - anything else / --json : passed through verbatim (you supply the right shape)

Category resolution needs the app config, so create-item/update-item fetch
GET /app/{app_id} once to map field external_ids to types and option labels.
For update-item the app id is read from the item itself.

Examples:
  podio_write.py create-item --app 12345678 --field title="Acme Roofing" \
      --field phone=+14055551234 --field status="New Lead"
  podio_write.py update-item 3303283090 --field status="Invoice Sent"
  podio_write.py comment 3303283090 "Invoice emailed to the owner"
  podio_write.py task "Call Acme back" --item 3303283090 --due 2026-07-01
  podio_write.py complete-task 987654321

Add --json-out to any command to print the full Podio response object.
Reads credentials from ~/.hermes/.env (PODIO_* vars), same as podio_lookup.py.
"""

import argparse
import json
import re
import sys

import requests

# Reuse the exact auth + refresh-on-401 helpers. No token logic is duplicated.
from podio_lookup import (
    PODIO_API,
    TIMEOUT,
    _api_get,
    _api_post,
    _api_put,
    get_access_token,
)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def _handle(resp: requests.Response, verb: str) -> dict:
    """Surface Podio's error body clearly; exit non-zero on failure."""
    if resp.status_code in (200, 201, 204):
        if resp.status_code == 204 or not resp.text:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}
    # Podio error bodies look like:
    #   {"error": "...", "error_description": "...", "error_detail": {...}}
    detail = resp.text[:600]
    try:
        body = resp.json()
        parts = [body.get("error_description") or body.get("error") or ""]
        if body.get("error_detail"):
            parts.append(json.dumps(body["error_detail"]))
        detail = " ".join(p for p in parts if p) or detail
    except ValueError:
        pass
    print(f"error: Podio {resp.status_code} on {verb}: {detail}", file=sys.stderr)
    sys.exit(1)


def _require_token() -> None:
    """Guard: missing token -> exit 2 (matches the house convention)."""
    try:
        token = get_access_token()
    except SystemExit:
        # get_access_token / _get_creds call sys.exit(1) when env is absent;
        # normalize that to the missing-token exit code.
        print("error: no Podio access token available (PODIO_ACCESS_TOKEN missing). "
              "Reconnect Podio in the NoDesk portal.", file=sys.stderr)
        sys.exit(2)
    if not token:
        print("error: no Podio access token available (PODIO_ACCESS_TOKEN missing). "
              "Reconnect Podio in the NoDesk portal.", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# App config + field-value coercion
# ---------------------------------------------------------------------------

def _get_app_config(app_id: int) -> dict:
    """Map external_id -> {type, field_id, options: {label_lower: option_id}}."""
    resp = _api_get(f"{PODIO_API}/app/{app_id}")
    data = _handle(resp, f"GET /app/{app_id}")
    fields = {}
    for f in data.get("fields", []):
        ext = f.get("external_id", "")
        cfg = f.get("config", {}) or {}
        settings = cfg.get("settings", {}) or {}
        options = {}
        for opt in settings.get("options", []) or []:
            if opt.get("status") == "deleted":
                continue
            label = (opt.get("text") or "").strip()
            if label:
                options[label.lower()] = opt.get("id")
        fields[ext] = {
            "type": f.get("type", ""),
            "field_id": f.get("field_id"),
            "options": options,
        }
    return fields


def _coerce_value(raw: str, ftype: str, options: dict):
    """Turn a string --field value into the Podio shape for its field type."""
    if ftype in ("text", "number", "money", "calculation", "duration"):
        return raw
    if ftype in ("phone", "email"):
        return [{"type": "other", "value": raw}]
    if ftype == "date":
        # Accept "YYYY-MM-DD" or a full "YYYY-MM-DD HH:MM:SS".
        return {"start": raw}
    if ftype in ("category", "question", "state"):
        # Accept a label (case-insensitive) or a literal option id.
        if raw.isdigit():
            return int(raw)
        opt = options.get(raw.strip().lower())
        if opt is None:
            valid = ", ".join(sorted(options.keys())) or "(none defined)"
            print(f"error: '{raw}' is not a valid option for this category field. "
                  f"Valid labels: {valid}", file=sys.stderr)
            sys.exit(1)
        return opt
    # app reference / contact / others: best-effort pass-through (usually an id).
    if raw.isdigit():
        return int(raw)
    return raw


def _parse_field_inputs(field_args, json_arg) -> dict:
    """Syntactic parse of --field / --json into a {key: raw_value} map.

    Done BEFORE any network call so bad input fails fast (exit 1) without a
    wasted API round-trip. Values that came from --json keep their parsed type;
    values from --field are raw strings to be coerced once the app config loads.
    """
    raw_map = {}

    if json_arg:
        raw = sys.stdin.read() if json_arg == "-" else json_arg
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"error: --json is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(parsed, dict):
            print("error: --json must be a JSON object of {field: value}", file=sys.stderr)
            sys.exit(1)
        for key, val in parsed.items():
            raw_map[key] = ("json", val)

    for pair in field_args or []:
        if "=" not in pair:
            print(f"error: --field expects key=value, got '{pair}'", file=sys.stderr)
            sys.exit(1)
        key, _, val = pair.partition("=")
        raw_map[key.strip()] = ("field", val)

    if not raw_map:
        print("error: no fields supplied (use --field key=value or --json)", file=sys.stderr)
        sys.exit(1)
    return raw_map


def _build_fields(raw_map: dict, app_cfg: dict) -> dict:
    """Coerce the syntactically-parsed inputs into Podio's value shapes."""
    fields = {}
    for key, (source, val) in raw_map.items():
        cfg = app_cfg.get(key)
        if source == "json":
            # Coerce only bare scalars against a known field; otherwise trust the caller.
            if cfg and isinstance(val, (str, int)) and not isinstance(val, bool):
                fields[key] = _coerce_value(str(val), cfg["type"], cfg["options"])
            else:
                fields[key] = val
        else:  # --field: always a raw string
            if cfg is None:
                fields[key] = val  # unknown external_id: let Podio validate
            else:
                fields[key] = _coerce_value(val, cfg["type"], cfg["options"])
    return fields


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_create_item(args) -> None:
    raw_map = _parse_field_inputs(args.field, args.json_in)
    app_cfg = _get_app_config(args.app)
    fields = _build_fields(raw_map, app_cfg)
    resp = _api_post(f"{PODIO_API}/item/app/{args.app}/", {"fields": fields})
    data = _handle(resp, f"create item in app {args.app}")
    if args.json_out:
        print(json.dumps(data, indent=2))
    else:
        title = data.get("title", "")
        link = data.get("link", "")
        print(f"Created item {data.get('item_id', '?')}" + (f"  {title}" if title else "")
              + (f"  {link}" if link else ""))


def _item_app_id(item_id: int) -> int:
    resp = _api_get(f"{PODIO_API}/item/{item_id}")
    data = _handle(resp, f"read item {item_id}")
    app_id = (data.get("app") or {}).get("app_id")
    if not app_id:
        print(f"error: could not determine app for item {item_id}", file=sys.stderr)
        sys.exit(1)
    return app_id


def cmd_update_item(args) -> None:
    raw_map = _parse_field_inputs(args.field, args.json_in)
    app_id = _item_app_id(int(args.item_id))
    app_cfg = _get_app_config(app_id)
    fields = _build_fields(raw_map, app_cfg)
    resp = _api_put(f"{PODIO_API}/item/{args.item_id}/value/", {"fields": fields})
    data = _handle(resp, f"update item {args.item_id}")
    if args.json_out:
        print(json.dumps(data, indent=2))
    else:
        changed = ", ".join(fields.keys())
        print(f"Updated item {args.item_id} ({changed})")


def cmd_comment(args) -> None:
    resp = _api_post(f"{PODIO_API}/comment/item/{args.item_id}/", {"value": args.text})
    data = _handle(resp, f"comment on item {args.item_id}")
    if args.json_out:
        print(json.dumps(data, indent=2))
    else:
        print(f"Commented on item {args.item_id} (comment {data.get('comment_id', '?')})")


def cmd_task(args) -> None:
    payload = {"text": args.title}
    if args.due:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.due):
            print("error: --due must be YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
        payload["due_date"] = args.due
    if args.item:
        # Attach the task to an item via the ref params Podio's /task/ accepts.
        payload["ref_type"] = "item"
        payload["ref_id"] = int(args.item)
    resp = _api_post(f"{PODIO_API}/task/", payload)
    data = _handle(resp, "create task")
    # /task/ returns a list with a single created task.
    task = data[0] if isinstance(data, list) and data else data
    if args.json_out:
        print(json.dumps(data, indent=2))
    else:
        tid = task.get("task_id", "?") if isinstance(task, dict) else "?"
        print(f"Created task {tid}: {args.title}"
              + (f"  due {args.due}" if args.due else "")
              + (f"  on item {args.item}" if args.item else ""))


def cmd_complete_task(args) -> None:
    resp = _api_post(f"{PODIO_API}/task/{args.task_id}/complete", {})
    data = _handle(resp, f"complete task {args.task_id}")
    if args.json_out:
        print(json.dumps(data, indent=2))
    else:
        print(f"Completed task {args.task_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Podio writer: create/update items, comment, create/complete tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--json-out", action="store_true", help="print the full Podio response object")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-item", help="create an item in an app")
    c.add_argument("--app", type=int, required=True, metavar="APP_ID", help="target app id")
    c.add_argument("--field", action="append", metavar="ext_id=value",
                   help="field value (repeatable); e.g. --field title=\"Acme\"")
    c.add_argument("--json", dest="json_in", metavar="JSON",
                   help="field map as JSON (or '-' for stdin)")

    u = sub.add_parser("update-item", help="update field values on an item")
    u.add_argument("item_id")
    u.add_argument("--field", action="append", metavar="ext_id=value",
                   help="field value (repeatable)")
    u.add_argument("--json", dest="json_in", metavar="JSON",
                   help="field map as JSON (or '-' for stdin)")

    cm = sub.add_parser("comment", help="add a comment to an item")
    cm.add_argument("item_id")
    cm.add_argument("text")

    t = sub.add_parser("task", help="create a task (optionally linked to an item)")
    t.add_argument("title")
    t.add_argument("--item", metavar="ITEM_ID", help="link the task to this item")
    t.add_argument("--due", metavar="YYYY-MM-DD", help="due date")

    ct = sub.add_parser("complete-task", help="mark a task complete")
    ct.add_argument("task_id")

    args = p.parse_args()
    _require_token()

    try:
        {
            "create-item": cmd_create_item,
            "update-item": cmd_update_item,
            "comment": cmd_comment,
            "task": cmd_task,
            "complete-task": cmd_complete_task,
        }[args.cmd](args)
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
