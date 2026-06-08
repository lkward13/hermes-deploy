# lead-auto-text eval harness

Evals for the `skills/lead-auto-text` (Speed-to-Lead) skill. See the N4 design
brief for the full tier plan. This is **Tier 1** (PR 1): deterministic,
credential-free unit/contract tests for the skill's helper scripts.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
pytest
```

`pytest` runs green with **zero credentials and zero network** — every outbound
HTTP call (Facebook Graph, ClickSend) is stubbed with `responses`, the clock is
frozen with `freezegun`, and `leads.json` is redirected to a tmp file. An
unmocked outbound call fails the test by design.

## Fleet safety

These files ship in the repo and therefore land on customer VPSes (via the daily
`git reset --hard origin/main` pull job), but they are **inert**: nothing in
`bootstrap.sh` / `first_boot.sh` / `render_templates.py` pip-installs
`requirements-dev.txt` or executes `evals/`, and no cron runs pytest.

## Layout

- `conftest.py` — fake env (set before skill import), tmp `leads.json`, HTTP mock.
- `loader.py` — `load_fixture(name)` reads `fixtures/<name>.yaml`.
- `fixtures/` — one scenario per file (input payloads + expected outcomes).
- `test_*.py` — Tier 1 scenarios 3, 4, 5, 11, 12, 13 + a pinned business-hours boundary.

## Tiers not in this PR

- Tier 2 (recorded-transcript replay + contract-lint) — PR 3, brings the gate to ≥10.
- Tier 3 (LLM-judge rubric) — PR 4, nightly/non-gating, blocked on N1 (ICP).
