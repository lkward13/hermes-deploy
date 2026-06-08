"""Tier 1 — check_sms.py: lookback-window width determines whether a slightly
older inbound reply is seen (the polling-pitfalls missed-reply failure mode).

Scenario 12: a ~5-minute-old reply is missed by `--since 2`, caught by `--since 10`.
"""
import json
import sys
from datetime import datetime, timezone

from freezegun import freeze_time

from loader import load_fixture


def _run_check(mocked_responses_unused, since, capsys, monkeypatch):
    import check_sms

    monkeypatch.setattr(
        sys, "argv", ["check_sms.py", "--since", str(since), "--json"]
    )
    check_sms.main()
    return json.loads(capsys.readouterr().out)


def test_lookback_window_width(mocked_responses, capsys, monkeypatch):
    import check_sms

    fx = load_fixture("missed_reply_lookback")
    now = datetime.fromisoformat(fx["now_iso"])
    msg_ts = int(now.timestamp()) - fx["message_age_seconds"]

    payload = {
        "data": {
            "data": [
                {
                    "from": fx["inbound_message"]["from"],
                    "to": fx["inbound_message"]["to"],
                    "body": fx["inbound_message"]["body"],
                    "timestamp": str(msg_ts),
                }
            ]
        }
    }
    # One registration is reused across both calls within the mock context.
    mocked_responses.add(
        mocked_responses.GET, check_sms.INBOUND_URL, json=payload, status=200
    )

    with freeze_time(now.astimezone(timezone.utc)):
        narrow = _run_check(mocked_responses, fx["narrow_since"], capsys, monkeypatch)
        wide = _run_check(mocked_responses, fx["wide_since"], capsys, monkeypatch)

    assert len(narrow) == fx["expected"]["narrow_count"]
    assert len(wide) == fx["expected"]["wide_count"]
