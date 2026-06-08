"""Tier 1 — poll_leads.py: new-lead discovery, dedup, and missing-phone drop.

Scenarios:
  3 — duplicate lead (known fb_lead_id) is not re-surfaced.
  4 — lead with no phone number is dropped, no SMS attempted.
"""
import json

from loader import load_fixture


def _run_poll(mocked_responses, graph_data, capsys):
    import poll_leads

    mocked_responses.add(
        mocked_responses.GET,
        poll_leads.GRAPH_URL,
        json={"data": graph_data},
        status=200,
    )
    rc = poll_leads.main()
    out = json.loads(capsys.readouterr().out)
    return rc, out


def test_duplicate_lead_not_resurfaced(tmp_leads, mocked_responses, capsys):
    fx = load_fixture("duplicate_lead")
    tmp_leads.write_text(json.dumps(fx["seed_leads"]))

    rc, out = _run_poll(mocked_responses, fx["graph_response"]["data"], capsys)

    assert rc == 0
    assert out["total_fetched"] == fx["expected"]["total_fetched"]
    new_ids = [lead["fb_lead_id"] for lead in out["new_leads"]]
    assert new_ids == fx["expected"]["new_lead_ids"]


def test_lead_missing_phone_is_dropped(tmp_leads, mocked_responses, capsys):
    fx = load_fixture("missing_phone")

    rc, out = _run_poll(mocked_responses, fx["graph_response"]["data"], capsys)

    assert rc == 0
    assert out["total_fetched"] == fx["expected"]["total_fetched"]
    assert out["new_leads"] == fx["expected"]["new_lead_ids"]  # empty list
