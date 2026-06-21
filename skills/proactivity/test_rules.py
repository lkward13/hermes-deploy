"""Library + engine-contract tests for the NoDesk proactivity rule library.

Validates every rule file in skills/proactivity/rules against the engine
contract declared in hermes_cli.nodesk_proactivity, and exercises the engine's
load_rules / run_tick on the hot path with fake (no-data) and benign-empty
RuleContext.run_skill stubs.

Pure stdlib + pytest. The fork's hermes_cli package lives at
/tmp/nodesk-fork-upgrade, so we put that on sys.path before importing.

House rule under test: zero em dashes (the long horizontal dash) in any rule
source file.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

# --- make "import hermes_cli.nodesk_proactivity" resolve against the fork -----
FORK_ROOT = "/tmp/nodesk-fork-upgrade"
if FORK_ROOT not in sys.path:
    sys.path.insert(0, FORK_ROOT)

import hermes_cli.nodesk_proactivity as engine  # noqa: E402
from hermes_cli.nodesk_proactivity import (  # noqa: E402
    Action,
    RuleContext,
    RuleSpec,
    load_rules,
    run_tick,
    AUTONOMY_LEVELS,
    CATEGORY_ORDER,
)

RULES_DIR = Path(
    "/Users/lukeward/Documents/Coding Projects/hermes-deploy/skills/proactivity/rules"
)

EM_DASH = "\u2014"  # the long horizontal dash, by codepoint so this file has none

NOW = datetime.datetime(2026, 6, 21, 15, 0, 0, tzinfo=datetime.timezone.utc)


# =============================================================================
# Fixtures / helpers
# =============================================================================

def _make_ctx(run_skill):
    """Build a RuleContext from the real contract dataclass."""
    return RuleContext(
        home=Path("/tmp/nodesk-proactivity-test-home"),
        env={},
        now=NOW,
        run_skill=run_skill,
        seen=lambda _eid: False,
    )


def _run_skill_none(*_args, **_kwargs):
    """Simulate no data / a missing skill: every fetch returns None."""
    return None


def _run_skill_empty(*_args, **_kwargs):
    """Simulate a present-but-empty integration: benign empty structures.

    Rules variously expect a list, a dict, or a JSON envelope, so return a value
    that is empty under any of those readings without raising.
    """
    return []


@pytest.fixture(scope="module")
def loaded_rules():
    mods = load_rules(RULES_DIR)
    assert mods, "load_rules returned no rules (expected the full library)"
    return mods


def _rule_source_files():
    return sorted(p for p in RULES_DIR.glob("*.py") if not p.name.startswith("_"))


# =============================================================================
# Library structure / RuleSpec contract
# =============================================================================

def test_rules_dir_exists():
    assert RULES_DIR.is_dir(), f"rules dir missing: {RULES_DIR}"


def test_every_source_file_loads(loaded_rules):
    """load_rules silently skips malformed modules, so cross-check that every
    non-underscore source file actually produced a loaded rule."""
    source_count = len(_rule_source_files())
    assert len(loaded_rules) == source_count, (
        f"loaded {len(loaded_rules)} rules but found {source_count} source files; "
        "some file failed to import or lacks a valid RULE/evaluate"
    )


def test_each_module_has_rulespec_and_evaluate(loaded_rules):
    for mod in loaded_rules:
        rule = getattr(mod, "RULE", None)
        assert isinstance(rule, RuleSpec), f"{mod.__name__}: RULE is not a RuleSpec"
        assert callable(getattr(mod, "evaluate", None)), (
            f"{mod.__name__}: evaluate is not callable"
        )


def test_rule_keys_unique(loaded_rules):
    keys = [mod.RULE.key for mod in loaded_rules]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"duplicate RULE.key values across the library: {dupes}"
    assert all(k and isinstance(k, str) for k in keys), "a RULE.key is empty/non-str"


def test_rule_category_valid(loaded_rules):
    for mod in loaded_rules:
        cat = mod.RULE.category
        assert cat in CATEGORY_ORDER, (
            f"{mod.RULE.key}: category {cat!r} not in CATEGORY_ORDER {sorted(CATEGORY_ORDER)}"
        )


def test_rule_default_autonomy_valid(loaded_rules):
    for mod in loaded_rules:
        lvl = mod.RULE.default_autonomy
        assert lvl in AUTONOMY_LEVELS, (
            f"{mod.RULE.key}: default_autonomy {lvl!r} not in {AUTONOMY_LEVELS}"
        )


def test_rule_providers_is_sequence(loaded_rules):
    for mod in loaded_rules:
        providers = mod.RULE.providers
        assert isinstance(providers, (tuple, list)), (
            f"{mod.RULE.key}: providers is {type(providers).__name__}, expected tuple/list"
        )
        assert all(isinstance(p, str) for p in providers), (
            f"{mod.RULE.key}: providers contains a non-str entry"
        )


# =============================================================================
# evaluate() contract: never raises, returns a list, under both stubs
# =============================================================================

@pytest.mark.parametrize(
    "run_skill,label",
    [(_run_skill_none, "no-data"), (_run_skill_empty, "benign-empty")],
)
def test_evaluate_never_raises_returns_list(loaded_rules, run_skill, label):
    ctx = _make_ctx(run_skill)
    for mod in loaded_rules:
        try:
            out = mod.evaluate(ctx)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"{mod.RULE.key}: evaluate() raised under {label} stub: {exc!r}")
        assert isinstance(out, list), (
            f"{mod.RULE.key}: evaluate() returned {type(out).__name__} under {label} stub, expected list"
        )


# =============================================================================
# No em dashes anywhere in rule source
# =============================================================================

def test_no_em_dash_in_rule_sources():
    offenders = []
    for path in _rule_source_files():
        text = path.read_text("utf-8")
        if EM_DASH in text:
            offenders.append(path.name)
    assert not offenders, f"em dash found in rule source files: {offenders}"


# =============================================================================
# Engine run_tick with a fake connected-provider set
# =============================================================================

def test_run_tick_with_fake_providers_returns_str(monkeypatch):
    """run_tick gates rules on _opener.detect_capabilities(). Inject a fake
    fully-connected set, point it at the real rules dir with a run_skill stub
    that returns no data, and assert it returns a string and never raises."""
    all_providers = sorted(
        {p for mod in load_rules(RULES_DIR) for p in mod.RULE.providers}
    )

    # Fake the provider gate to report everything connected.
    fake_opener = type("FakeOpener", (), {})()
    fake_opener.detect_capabilities = staticmethod(
        lambda env=None: {"connected": all_providers}
    )
    fake_opener._hermes_home = staticmethod(lambda: Path("/tmp/nodesk-proactivity-test-home"))
    monkeypatch.setattr(engine, "_opener", fake_opener)

    # Force every fetch to return no data so no real subprocess/integration runs.
    monkeypatch.setattr(
        engine, "_make_run_skill", lambda home, env: _run_skill_none
    )

    out = run_tick(
        home=Path("/tmp/nodesk-proactivity-test-home"),
        env={},
        rules_dir=RULES_DIR,
        now=NOW,
    )
    assert isinstance(out, str), f"run_tick returned {type(out).__name__}, expected str"


def test_run_tick_no_providers_connected_returns_str(monkeypatch):
    """With nothing connected, every rule is gated out: run_tick still returns a
    string (empty), never raises."""
    fake_opener = type("FakeOpener", (), {})()
    fake_opener.detect_capabilities = staticmethod(lambda env=None: {"connected": []})
    fake_opener._hermes_home = staticmethod(lambda: Path("/tmp/nodesk-proactivity-test-home"))
    monkeypatch.setattr(engine, "_opener", fake_opener)
    monkeypatch.setattr(engine, "_make_run_skill", lambda home, env: _run_skill_none)

    out = run_tick(
        home=Path("/tmp/nodesk-proactivity-test-home"),
        env={},
        rules_dir=RULES_DIR,
        now=NOW,
    )
    assert isinstance(out, str)
    assert out == "", "no providers connected should yield empty owner message"
