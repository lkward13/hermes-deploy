"""Tier 1 — lead_auto_text_cron.check_business_hours() boundary, DST-aware.

Locks the issue #8 fix: the gate uses America/Chicago, so the UTC->Central
offset is -6 under CST (Nov-Mar) and -5 under CDT (Mar-Nov). The winter cases in
the fixture fail against the old hardcoded UTC-5 code and pass against the
zoneinfo fix; the summer cases keep CDT behavior covered.
"""
from datetime import datetime, timezone

from freezegun import freeze_time

from loader import load_fixture


def test_business_hours_boundaries_are_dst_correct():
    import lead_auto_text_cron as cron

    fx = load_fixture("business_hours_boundary")
    for case in fx["cases"]:
        moment = datetime.fromisoformat(case["utc"]).replace(tzinfo=timezone.utc)
        with freeze_time(moment):
            assert cron.check_business_hours() is case["expected"], case["utc"]
