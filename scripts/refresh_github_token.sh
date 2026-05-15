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

# Write file-based gh auth so subprocesses don't need GH_TOKEN in env.
# Hermes strips GH_TOKEN from agent subprocess environments for security
# (see tools/environments/local.py blocklist), so file-based auth is the
# only way to make gh work inside agent terminal sessions.
HERMES_USER="${HERMES_USER:-hermes}"
GH_CONFIG_DIR="/home/${HERMES_USER}/.config/gh"
mkdir -p "${GH_CONFIG_DIR}"
cat > "${GH_CONFIG_DIR}/hosts.yml" <<HOSTS
github.com:
    oauth_token: ${new_token}
    git_protocol: https
    user: x-access-token
HOSTS
chown -R "${HERMES_USER}:${HERMES_USER}" "/home/${HERMES_USER}/.config" 2>/dev/null || true
chmod 600 "${GH_CONFIG_DIR}/hosts.yml"

# Also rewrite git's credential helper so git clone / push works without env
git config --global --replace-all credential.https://github.com.helper "" 2>/dev/null || true
git config --global --add credential.https://github.com.helper '!f() { echo "username=x-access-token"; echo "password='"${new_token}"'"; }; f' 2>/dev/null || true
sudo -u "${HERMES_USER}" git config --global --replace-all credential.https://github.com.helper "" 2>/dev/null || true
sudo -u "${HERMES_USER}" git config --global --add credential.https://github.com.helper '!f() { echo "username=x-access-token"; echo "password='"${new_token}"'"; }; f' 2>/dev/null || true

# Restart so the gateway picks up the new value (still useful for any
# in-process callers reading GITHUB_TOKEN from .env).
systemctl restart hermes-gateway 2>>"${LOG}" || true
