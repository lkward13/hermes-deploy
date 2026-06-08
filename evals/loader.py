"""Tiny fixture loader: read a scenario YAML from evals/fixtures/<name>.yaml."""
from pathlib import Path

import yaml

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)
