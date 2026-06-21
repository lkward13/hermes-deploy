#!/usr/bin/env python3
"""Chronos job runner for the NoDesk proactivity engine.

Runs one engine tick (health alerts + rule signals, both deduped) and prints the
owner-facing message to stdout. Chronos delivers stdout to the owner, so empty
output means "nothing worth saying this tick" (the common case, by design: dedup
+ per-rule cadence + materiality keep the agent quiet until something matters).

Registered as a no_agent chronos job (deterministic, no LLM call). Best-effort:
never raises, prints nothing on any failure. The engine lives in the agent
package (hermes_cli.nodesk_proactivity); the rule library lives under
$HERMES_HOME/skills/proactivity/rules.

House rule: zero em dashes anywhere.
"""

import sys


def main() -> int:
    try:
        from hermes_cli import nodesk_proactivity as proactivity
    except Exception:
        # Engine not present (older agent build): nothing to do, stay silent.
        return 0
    try:
        message = proactivity.run_tick()
    except Exception:
        message = ""
    if message and message.strip():
        sys.stdout.write(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
