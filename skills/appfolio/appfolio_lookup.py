#!/usr/bin/env python3
"""AppFolio Owner Portal read-only data layer.

AppFolio has no public API for owner-portal data (their API is partner-gated),
so the agent logs into the company owner portal with the Camofox browser and
this script reuses that *same authenticated session* to call the portal's
internal JSON endpoints under ``/oportal/api/`` directly. That is far more
reliable than scraping the React UI: the endpoints return clean structured
finance data.

SESSION MODEL (important)
-------------------------
This script does NOT log in. Logging in (email/password + 2FA) is a browser
step handled by the ``appfolio-owner-portal`` skill. That browser session's
cookies are persisted by Camofox to a Playwright storageState file. This
script loads those cookies and replays them with ``requests``. So the order is
always:

    1. browser: log into ``https://<company>.appfolio.com/oportal/`` (handles
       2FA + "remember this device"); Camofox persists the cookies.
    2. this script: read those cookies and hit ``/oportal/api/...``.

The owner-portal auth cookie (``_oportal_session``) is session-only and the
server expires it after a few hours of inactivity, so if this script gets a
login redirect it reports ``auth_expired`` and the agent must re-run the
browser login before retrying.

COOKIE SOURCES (first that resolves wins)
-----------------------------------------
  --cookies-file PATH   Playwright storageState JSON (``{"cookies":[...]}``)
  --user-id ID          Camofox managed-profile userId; reads that profile's
                        storage-state.json under CAMOFOX_PROFILE_DIR
                        (default ~/.camofox/profiles).
  APPFOLIO_STORAGE_STATE env var pointing at a storageState JSON file.

The company subdomain is taken from ``--company`` or inferred from the cookie
domains (``<company>.appfolio.com``).

USAGE
-----
    python appfolio_lookup.py whoami --user-id hermes_xxxx
    python appfolio_lookup.py ownerships --user-id hermes_xxxx
    python appfolio_lookup.py income   --start 06/01/2026 --end 06/30/2026 --user-id hermes_xxxx
    python appfolio_lookup.py summary  --start 06/01/2026 --end 06/30/2026 --user-id hermes_xxxx
    python appfolio_lookup.py transactions --start 06/01/2026 --end 06/30/2026 --limit 100

All output is JSON on stdout. Dates are MM/DD/YYYY (AppFolio's format).

HARD HOUSE RULE: zero em dashes anywhere. Use periods, commas, colons, parens.
NEEDS LIVE VALIDATION against a connected portal before fleet rollout: the
endpoint paths + field names below are taken from observed live sessions
(see references/), but response shapes should be confirmed on first real run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import requests

_TIMEOUT = 30
_API = "/oportal/api"


def _die(msg: str, *, code: str = "error", extra: Optional[dict] = None) -> None:
    out = {"ok": False, "code": code, "error": msg}
    if extra:
        out.update(extra)
    print(json.dumps(out))
    sys.exit(1)


# --------------------------------------------------------------------------
# Cookie loading
# --------------------------------------------------------------------------

def _profile_dir() -> Path:
    return Path(
        os.environ.get("CAMOFOX_PROFILE_DIR")
        or (Path.home() / ".camofox" / "profiles")
    )


def _normalize_user_id(user_id: str) -> str:
    """Mirror camofox-browser's profile-dir naming (md5 of the userId)."""
    return hashlib.md5(user_id.encode("utf-8")).hexdigest()


def _load_storage_state(args: argparse.Namespace) -> dict:
    # 1. explicit file
    path = args.cookies_file or os.environ.get("APPFOLIO_STORAGE_STATE")
    # 2. camofox managed profile
    if not path and args.user_id:
        cand = _profile_dir() / _normalize_user_id(args.user_id) / "storage-state.json"
        if cand.is_file():
            path = str(cand)
    if not path:
        _die(
            "no cookie source: pass --cookies-file, --user-id, or set "
            "APPFOLIO_STORAGE_STATE. Log into the portal with the browser first.",
            code="no_cookies",
        )
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        _die(f"could not read storage state {path}: {exc}", code="no_cookies")
    return {}


def _build_session(state: dict, company: Optional[str]) -> tuple[requests.Session, str]:
    cookies = state.get("cookies") or []
    if not cookies:
        _die("storage state has no cookies. Re-run the browser login.", code="no_cookies")

    # Infer the company subdomain from the appfolio cookie domains if not given.
    if not company:
        for c in cookies:
            dom = (c.get("domain") or "").lstrip(".")
            if dom.endswith(".appfolio.com") and dom != "appfolio.com":
                company = dom.split(".")[0]
                break
    if not company:
        _die("could not determine company subdomain. Pass --company.", code="no_company")

    sess = requests.Session()
    sess.headers.update({
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (NoDesk AppFolio owner-portal agent)",
    })
    for c in cookies:
        sess.cookies.set(
            c.get("name"), c.get("value"),
            domain=(c.get("domain") or "").lstrip("."),
            path=c.get("path") or "/",
        )
    return sess, company


def _get(sess: requests.Session, company: str, path: str, params: Optional[dict] = None) -> Any:
    url = f"https://{company}.appfolio.com{path}"
    try:
        r = sess.get(url, params=params or {}, timeout=_TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        _die(f"request failed: {exc}", code="network")
    # A redirect to the login page means the session expired.
    loc = r.headers.get("Location", "")
    if r.status_code in (301, 302, 303, 307, 308) and ("log_in" in loc or "users" in loc):
        _die(
            "AppFolio session expired (redirected to login). Re-run the browser "
            "login (email/password + 2FA) before retrying.",
            code="auth_expired",
            extra={"location": loc},
        )
    if r.status_code == 401 or r.status_code == 403:
        _die("not authenticated for this endpoint.", code="auth_expired",
             extra={"status": r.status_code})
    if r.status_code >= 400:
        _die(f"HTTP {r.status_code} for {path}", code="http_error",
             extra={"status": r.status_code, "body": r.text[:300]})
    ctype = r.headers.get("Content-Type", "")
    if "json" not in ctype:
        # Got HTML where JSON was expected. Usually an auth/redirect wall.
        _die("expected JSON, got HTML (likely an auth wall or wrong endpoint).",
             code="auth_expired", extra={"path": path})
    try:
        return r.json()
    except ValueError:
        _die("response was not valid JSON.", code="bad_response", extra={"path": path})


def _ok(data: Any, **meta) -> None:
    out = {"ok": True}
    out.update(meta)
    out["data"] = data
    print(json.dumps(out, default=str))


def _amount(rows: list, *keys: str) -> float:
    total = 0.0
    for row in rows or []:
        for k in keys:
            v = row.get(k)
            if v is not None:
                try:
                    total += float(v)
                except (TypeError, ValueError):
                    pass
                break
    return round(total, 2)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_whoami(sess, company, args):
    # Cheap authenticated probe: ownerships should return the owner's entities.
    data = _get(sess, company, f"{_API}/owner_ownerships")
    _ok(data, company=company, endpoint="owner_ownerships")


def cmd_ownerships(sess, company, args):
    _ok(_get(sess, company, f"{_API}/owner_ownerships"), company=company)


def _date_params(args) -> dict:
    if not args.start or not args.end:
        _die("--start and --end (MM/DD/YYYY) are required for this command.",
             code="bad_args")
    return {"start_on": args.start, "end_on": args.end}


def cmd_income(sess, company, args):
    _ok(_get(sess, company, f"{_API}/owner_income", _date_params(args)),
        company=company, range=[args.start, args.end])


def cmd_expenses(sess, company, args):
    _ok(_get(sess, company, f"{_API}/owner_expenses", _date_params(args)),
        company=company, range=[args.start, args.end])


def cmd_income_balances(sess, company, args):
    _ok(_get(sess, company, f"{_API}/owner_income_balances", _date_params(args)),
        company=company, range=[args.start, args.end])


def cmd_expense_balances(sess, company, args):
    _ok(_get(sess, company, f"{_API}/owner_expenses_balances", _date_params(args)),
        company=company, range=[args.start, args.end])


def cmd_transactions(sess, company, args):
    params = _date_params(args)
    params["limit"] = args.limit
    params["offset"] = args.offset
    _ok(_get(sess, company, f"{_API}/owner_transactions", params),
        company=company, range=[args.start, args.end])


def cmd_summary(sess, company, args):
    """Net cash flow for the period: sum(income) - sum(expenses)."""
    p = _date_params(args)
    income = _get(sess, company, f"{_API}/owner_income", p)
    expenses = _get(sess, company, f"{_API}/owner_expenses", p)
    inc_rows = income if isinstance(income, list) else income.get("data") or income.get("items") or []
    exp_rows = expenses if isinstance(expenses, list) else expenses.get("data") or expenses.get("items") or []
    gross_in = _amount(inc_rows, "totalAmount", "amount", "total")
    gross_out = _amount(exp_rows, "totalAmount", "amount", "total")
    _ok({
        "gross_income": gross_in,
        "gross_expenses": gross_out,
        "net_cash_flow": round(gross_in - gross_out, 2),
        "income_rows": len(inc_rows),
        "expense_rows": len(exp_rows),
    }, company=company, range=[args.start, args.end],
        note="includes negative income (e.g. NSF reversals) since they reduce cash in")


_COMMANDS = {
    "whoami": cmd_whoami,
    "ownerships": cmd_ownerships,
    "income": cmd_income,
    "expenses": cmd_expenses,
    "income-balances": cmd_income_balances,
    "expense-balances": cmd_expense_balances,
    "transactions": cmd_transactions,
    "summary": cmd_summary,
}


def main() -> None:
    p = argparse.ArgumentParser(description="AppFolio Owner Portal read-only data layer.")
    p.add_argument("command", choices=sorted(_COMMANDS.keys()))
    p.add_argument("--user-id", help="Camofox managed-profile userId (loads its persisted cookies).")
    p.add_argument("--cookies-file", help="Path to a Playwright storageState JSON.")
    p.add_argument("--company", help="AppFolio subdomain (e.g. hometownoklahoma). Inferred if omitted.")
    p.add_argument("--start", help="Period start MM/DD/YYYY.")
    p.add_argument("--end", help="Period end MM/DD/YYYY.")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--offset", type=int, default=0)
    args = p.parse_args()

    state = _load_storage_state(args)
    sess, company = _build_session(state, args.company)
    _COMMANDS[args.command](sess, company, args)


if __name__ == "__main__":
    main()
