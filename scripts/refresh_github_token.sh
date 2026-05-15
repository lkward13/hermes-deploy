#!/usr/bin/env bash
# Refresh GITHUB_TOKEN / GH_TOKEN in ~/.hermes/.env every ~50min so it stays
# valid (GitHub App installation tokens expire after 1hr).
# Run via cron. Restart hermes-gateway only if the token actually changed so
# we don't churn the service.

set -e
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENV_FILE="${HERMES_HOME}/.env"
LOG="${HERMES_HOME}/github-token-refresh.log"

# shellcheck disable=SC1090
set -a; . "${ENV_FILE}"; set +a

if [ -z "${GITHUB_TOKEN_ENDPOINT:-}" ] || [ -z "${HERMES_CLIENT_ID:-}" ] || [ -z "${GITHUB_INSTALLATION_ID:-}" ]; then
  # GitHub not configured for this client — nothing to do.
  exit 0
fi

response=$(curl -fsS -H "X-Hermes-Token: ${HERMES_CLIENT_ID}" "${GITHUB_TOKEN_ENDPOINT}" 2>>"${LOG}" || true)
new_token=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('token',''))" 2>/dev/null || true)

if [ -z "$new_token" ]; then
  echo "$(date -Iseconds) refresh failed: $response" >> "${LOG}"
  exit 1
fi

if [ "$new_token" = "${GITHUB_TOKEN:-}" ]; then
  exit 0
fi

# Rewrite GITHUB_TOKEN and GH_TOKEN lines in place
python3 - "$new_token" "$ENV_FILE" <<'PY'
import re, sys
new_token, env_path = sys.argv[1], sys.argv[2]
with open(env_path) as f:
    content = f.read()
for key in ("GITHUB_TOKEN", "GH_TOKEN"):
    pat = rf"^{key}=.*$"
    repl = f"{key}='{new_token}'"
    if re.search(pat, content, re.MULTILINE):
        content = re.sub(pat, repl, content, flags=re.MULTILINE)
    else:
        content += f"\n{repl}\n"
with open(env_path, "w") as f:
    f.write(content)
PY

echo "$(date -Iseconds) refreshed token" >> "${LOG}"

# Restart so the gateway picks up the new value
systemctl restart hermes-gateway 2>>"${LOG}" || true
