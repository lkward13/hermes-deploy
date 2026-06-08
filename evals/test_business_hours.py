"""Tier 1 (optional 7th) — lead_auto_text_cron.check_business_hours() boundary.

PINNED to the current hardcoded UTC-5 behavior. This is a regression anchor for
a KNOWN bug: UTC-5 is wrong under Central Standard Time (Nov-Mar, should be
UTC-6). See the hermes-deploy DST issue. When that is fixed, the fixture and
these expectations change in the same PR — which is the point: the fix becomes
test-driven instead of silent.
"""
from datetime import datetime, timezone

from freezegun import freeze_time

from loader import load_fixture


def test_business_hours_boundaries_pinned_to_utc_minus_5():
    import lead_auto_text_cron as cron

    fx = load_fixture("business_hours_boundary")
    for case in fx["cases"]:
        moment = datetime.fromisoformat(case["utc"]).replace(tzinfo=timezone.utc)
        with freeze_time(moment):
            assert cron.check_business_hours() is case["expected"], case["utc"]
