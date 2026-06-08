"""Tier 1 — send_sms.py: a provider failure must never look like success.

Scenario 5 (two facets):
  - HTTP 200 with a non-SUCCESS per-message status -> return code 1.
  - HTTP error status (e.g. 400) -> raise_for_status propagates; no false success.
"""
import sys

import pytest
import requests

from loader import load_fixture


def test_non_success_status_returns_nonzero(mocked_responses, monkeypatch):
    import send_sms

    fx = load_fixture("provider_failure")
    mocked_responses.add(
        mocked_responses.POST,
        send_sms.API_URL,
        json=fx["clicksend_response"],
        status=200,
    )
    monkeypatch.setattr(
        sys, "argv", ["send_sms.py", "--to", "+15551234567", "--body", "hi"]
    )

    assert send_sms.main() == fx["expected"]["return_code"]


def test_http_error_propagates(mocked_responses, monkeypatch):
    import send_sms

    mocked_responses.add(
        mocked_responses.POST,
        send_sms.API_URL,
        json={"error": "bad request"},
        status=400,
    )
    monkeypatch.setattr(
        sys, "argv", ["send_sms.py", "--to", "+15551234567", "--body", "hi"]
    )

    with pytest.raises(requests.HTTPError):
        send_sms.main()
