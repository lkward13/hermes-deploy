"""Shared fixtures for the lead-auto-text eval harness (Tier 1, deterministic).

Design notes:
- The skill scripts capture configuration from os.environ AT IMPORT TIME
  (poll_leads.py builds GRAPH_URL from FB_FORM_ID on module load; send_sms.py /
  check_sms.py read CLICKSEND_* at module load). So fake credentials must be set
  here, before any test module imports those scripts. conftest.py is imported by
  pytest before test collection, which guarantees the ordering.
- No live credentials, no network: every outbound HTTP call is stubbed via the
  `mocked_responses` fixture. An unmocked call raises ConnectionError and fails
  the test (responses default behavior).
- leads.json is redirected to a per-test tmp file by monkeypatching the module
  globals — no production code change required.
"""
import os
import sys
from pathlib import Path

# --- Fake env, set before skill modules are imported (see module docstring) ---
_FAKE_ENV = {
    "FB_FORM_ID": "TESTFORM",
    "FB_PAGE_ACCESS_TOKEN": "test-fb-token",
    "CLICKSEND_USERNAME": "test-user",
    "CLICKSEND_API_KEY": "test-key",
    "CLICKSEND_FROM": "+15550001111",
    "BUSINESS_NAME": "Test Co",
    "OWNER_NAME": "Owner",
    "OWNER_PHONE": "+15550002222",
    "ADMIN_NAME": "Admin",
    "ADMIN_PHONE": "+15550003333",
    "AGENT_SUBAGENT_NAME": "Richard",
}
for _k, _v in _FAKE_ENV.items():
    os.environ.setdefault(_k, _v)

# --- Make the skill + scripts importable by bare module name ---
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "lead-auto-text"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _p in (SKILL_DIR, SCRIPTS_DIR):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import pytest  # noqa: E402
import responses  # noqa: E402


@pytest.fixture
def mocked_responses():
    """RequestsMock context: any unregistered outbound HTTP call fails the test."""
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def tmp_leads(tmp_path, monkeypatch):
    """Redirect both poll_leads and lead_state at an isolated leads.json.

    Returns the Path so a test can pre-seed it before exercising the scripts.
    """
    import lead_state
    import poll_leads

    leads_path = tmp_path / "leads.json"
    monkeypatch.setattr(lead_state, "LEADS_FILE", str(leads_path))
    monkeypatch.setattr(poll_leads, "LEADS_FILE", str(leads_path))
    return leads_path
