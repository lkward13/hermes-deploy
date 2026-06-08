"""Tier 1 — lead_state.py: phone normalization and the concurrency lock.

Scenarios:
  11 — concurrent handling: a second lock within the 120s TTL returns
       ALREADY_LOCKED (so a duplicate delegation/reply is prevented); a lock
       older than the TTL is treated as stale and re-acquired.
  13 — phone normalization: assorted formats map to one E.164 key.
"""
from datetime import timedelta
from types import SimpleNamespace

from freezegun import freeze_time

from loader import load_fixture


def test_phone_normalization(tmp_leads):
    import lead_state

    fx = load_fixture("phone_normalization")
    expected = fx["expected_normalized"]
    for raw in fx["cases"]:
        assert lead_state.normalize_phone(raw) == expected


def _add_lead(lead_state, phone):
    lead_state.cmd_add(
        SimpleNamespace(
            name="John", phone=phone, email="", source="facebook", fb_lead_id=""
        )
    )


def test_second_lock_within_ttl_is_already_locked(tmp_leads, capsys):
    import lead_state

    phone = "+15551112222"
    _add_lead(lead_state, phone)
    capsys.readouterr()

    lead_state.cmd_lock(SimpleNamespace(phone=phone))
    assert capsys.readouterr().out.strip() == "LOCKED"

    lead_state.cmd_lock(SimpleNamespace(phone=phone))
    assert capsys.readouterr().out.strip() == "ALREADY_LOCKED"


def test_stale_lock_past_ttl_is_reacquired(tmp_leads, capsys):
    import lead_state

    phone = "+15551112222"
    with freeze_time("2026-06-07 12:00:00") as frozen:
        _add_lead(lead_state, phone)
        capsys.readouterr()

        lead_state.cmd_lock(SimpleNamespace(phone=phone))
        assert capsys.readouterr().out.strip() == "LOCKED"

        # Advance past the 120s lock TTL: the prior lock is now stale.
        frozen.tick(delta=timedelta(seconds=121))
        lead_state.cmd_lock(SimpleNamespace(phone=phone))
        assert capsys.readouterr().out.strip() == "LOCKED"
