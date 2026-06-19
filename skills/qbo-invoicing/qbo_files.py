#!/usr/bin/env python3
"""
QuickBooks Online — document PDFs + attachments.

  pdf          GET /v3/company/{realm}/{Entity}/{id}/pdf   → save the PDF
  attach       POST /v3/company/{realm}/upload (multipart)  → upload a file and
               link it to a transaction via the Attachable API
  attachments  list files attached to a given transaction

Examples:
  qbo_files.py pdf Invoice 145                       # -> ./Invoice-145.pdf
  qbo_files.py pdf Estimate 88 --out /tmp/quote.pdf
  qbo_files.py attach Invoice 145 /path/to/receipt.jpg --note "Signed delivery slip"
  qbo_files.py attachments Invoice 145

Reuses qbo_auth.py (OAuth auto-refresh) + qbo_config.py (base URL).
"""

import argparse
import json
import mimetypes
import os
import sys

import requests

from qbo_auth import get_access_token, get_realm_id
from qbo_config import get_base_url

TIMEOUT = 60
MINOR_VERSION = "73"


def _bearer() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def _url(path: str) -> str:
    return f"{get_base_url()}/v3/company/{get_realm_id()}/{path}"


def _fault(resp: requests.Response) -> None:
    if resp.status_code == 401:
        print("error: 401 Unauthorized — reconnect QuickBooks in the NoDesk portal.", file=sys.stderr)
        sys.exit(3)
    if resp.status_code >= 400:
        try:
            fault = resp.json().get("Fault", {})
            errs = "; ".join(e.get("Message", "") for e in fault.get("Error", []))
            print(f"error: QBO {resp.status_code}: {errs or resp.text[:300]}", file=sys.stderr)
        except ValueError:
            print(f"error: QBO {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        sys.exit(1)


def cmd_pdf(args) -> None:
    resp = requests.get(
        _url(f"{args.entity.lower()}/{args.id}/pdf"),
        headers={**_bearer(), "Accept": "application/pdf"},
        params={"minorversion": MINOR_VERSION},
        timeout=TIMEOUT,
    )
    _fault(resp)
    out = args.out or f"{args.entity}-{args.id}.pdf"
    with open(out, "wb") as f:
        f.write(resp.content)
    print(f"Saved {args.entity} {args.id} PDF → {out} ({len(resp.content):,} bytes)")


def cmd_attach(args) -> None:
    if not os.path.isfile(args.file):
        print(f"error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    mime = mimetypes.guess_type(args.file)[0] or "application/octet-stream"
    fname = os.path.basename(args.file)
    meta = {
        "AttachableRef": [{"EntityRef": {"type": args.entity, "value": str(args.id)}}],
        "FileName": fname,
        "ContentType": mime,
    }
    if args.note:
        meta["Note"] = args.note
    with open(args.file, "rb") as fh:
        files = {
            "file_metadata_01": (None, json.dumps(meta), "application/json"),
            "file_content_01": (fname, fh, mime),
        }
        resp = requests.post(
            _url("upload"),
            headers={**_bearer(), "Accept": "application/json"},
            files=files,
            timeout=TIMEOUT,
        )
    _fault(resp)
    data = resp.json()
    if args.json:
        print(json.dumps(data, indent=2))
        return
    att = (data.get("AttachableResponse") or [{}])[0].get("Attachable", {})
    print(f"Attached {fname} ({mime}) to {args.entity} {args.id}  attachable_id={att.get('Id', '?')}")


def cmd_attachments(args) -> None:
    resp = requests.get(
        _url("query"),
        headers={**_bearer(), "Accept": "application/json"},
        params={"query": "SELECT * FROM Attachable MAXRESULTS 1000", "minorversion": MINOR_VERSION},
        timeout=TIMEOUT,
    )
    _fault(resp)
    rows = resp.json().get("QueryResponse", {}).get("Attachable", [])
    matches = [
        a for a in rows
        if any((ref.get("EntityRef") or {}).get("value") == str(args.id)
                and (ref.get("EntityRef") or {}).get("type", "").lower() == args.entity.lower()
                for ref in a.get("AttachableRef", []))
    ]
    if args.json:
        print(json.dumps(matches, indent=2))
        return
    if not matches:
        print(f"No attachments on {args.entity} {args.id}.")
        return
    for a in matches:
        print(f"- {a.get('Id')}  {a.get('FileName', a.get('Note', '(note)'))}  {a.get('ContentType', '')}  {a.get('Size', '')}b")
    print(f"({len(matches)} attachment(s))")


def main() -> int:
    p = argparse.ArgumentParser(description="QuickBooks Online — PDFs + attachments")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("pdf", help="download a transaction PDF")
    pf.add_argument("entity")
    pf.add_argument("id")
    pf.add_argument("--out", help="output path (default ./Entity-Id.pdf)")

    at = sub.add_parser("attach", help="upload + link a file to a transaction")
    at.add_argument("entity")
    at.add_argument("id")
    at.add_argument("file")
    at.add_argument("--note")

    al = sub.add_parser("attachments", help="list files attached to a transaction")
    al.add_argument("entity")
    al.add_argument("id")

    args = p.parse_args()
    try:
        {"pdf": cmd_pdf, "attach": cmd_attach, "attachments": cmd_attachments}[args.cmd](args)
    except requests.RequestException as exc:
        print(f"error: network failure: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
