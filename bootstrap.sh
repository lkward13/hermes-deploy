#!/usr/bin/env bash
set -euo pipefail

HERMES_USER="${HERMES_USER:-hermes}"
HERMES_HOME="${HERMES_HOME:-/home/${HERMES_USER}/.hermes}"
HERMES_AGENT_REPO="${HERMES_AGENT_REPO:-https://github.com/NousResearch/hermes-agent.git}"
HERMES_AGENT_REF="${HERMES_AGENT_REF:-b816fd4e2}"
HERMES_DEPLOY_REPO="${HERMES_DEPLOY_REPO:-}"
HERMES_DEPLOY_REF="${HERMES_DEPLOY_REF:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "bootstrap.sh must run as root" >&2
  exit 1
fi

if [[ -z "${HERMES_DEPLOY_REPO}" ]]; then
  echo "HERMES_DEPLOY_REPO is required" >&2
  exit 1
fi

echo "[hermes-bootstrap] Installing system packages"
apt-get \
  -o Acquire::Check-Valid-Until=false \
  -o Acquire::Check-Date=false \
  update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates \
  curl \
  git \
  jq \
  python3 \
  python3-pip \
  python3-venv \
  rsync

if ! command -v useradd >/dev/null 2>&1; then
  echo "[hermes-bootstrap] useradd unavailable; falling back to root-mode install"
  HERMES_USER="root"
  HERMES_HOME="/root/.hermes"
fi

if [[ "${HERMES_USER}" != "root" ]] && ! id "${HERMES_USER}" >/dev/null 2>&1; then
  echo "[hermes-bootstrap] Creating user ${HERMES_USER}"
  useradd --create-home --shell /bin/bash "${HERMES_USER}"
fi

mkdir -p "${HERMES_HOME}"
if [[ "${HERMES_USER}" != "root" ]]; then
  chown -R "${HERMES_USER}:${HERMES_USER}" "$(dirname "${HERMES_HOME}")"
fi

run_as_hermes() {
  if [[ "${HERMES_USER}" == "root" ]] || ! command -v runuser >/dev/null 2>&1; then
    bash -lc "$*"
  else
    runuser -u "${HERMES_USER}" -- bash -lc "$*"
  fi
}

echo "[hermes-bootstrap] Cloning deploy repo"
if [[ -d "${HERMES_HOME}/.git" ]]; then
  run_as_hermes "cd '${HERMES_HOME}' && git fetch origin && git checkout '${HERMES_DEPLOY_REF}'"
else
  # NoDesk's credential_sync may have raced ahead and written
  # /home/hermes/.hermes/.env before this script reached the clone step.
  # `rm -rf .../*` misses dotfiles (.env, .codex/, etc.), so git clone
  # would fail with "destination ... not empty". Nuke the dir entirely;
  # render_templates.py re-creates .env from env vars later in this script.
  rm -rf "${HERMES_HOME:?}"
  run_as_hermes "git clone '${HERMES_DEPLOY_REPO}' '${HERMES_HOME}' && cd '${HERMES_HOME}' && git checkout '${HERMES_DEPLOY_REF}'"
fi

echo "[hermes-bootstrap] Cloning Hermes agent"
if [[ -d "${HERMES_HOME}/hermes-agent/.git" ]]; then
  run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && git fetch origin && git checkout '${HERMES_AGENT_REF}'"
else
  run_as_hermes "git clone '${HERMES_AGENT_REPO}' '${HERMES_HOME}/hermes-agent' && cd '${HERMES_HOME}/hermes-agent' && git checkout '${HERMES_AGENT_REF}'"
fi

echo "[hermes-bootstrap] Creating virtualenv"
run_as_hermes "python3 -m venv '${HERMES_HOME}/hermes-agent/venv'"
# pip 26.x writes its editable path-hook file relative to CWD, not to
# site-packages. When bootstrap.sh runs as root from /root (cloud-init's
# default), the hermes user can't write there and pip exits with
# `Permission denied: '__editable__.<pkg>.finder.__path_hook__'`. cd to
# HERMES_HOME/hermes-agent first — hermes owns it.
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/python' -m pip install --upgrade pip wheel setuptools"
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/python' -m pip install slack-bolt slack-sdk"
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/pip' install -e ."
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/pip' install python-dotenv requests python-telegram-bot"

echo "[hermes-bootstrap] Installing voice extras (TTS + STT)"
# edge-tts: free Microsoft TTS for voice replies (~5MB).
# faster-whisper: local STT so clients can leave voice notes (~200MB pkg,
# ~500MB for the default model downloaded on first use).
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/pip' install --no-build-isolation edge-tts faster-whisper sounddevice numpy"

echo "[hermes-bootstrap] Installing gh (GitHub CLI)"
if ! command -v gh >/dev/null 2>&1; then
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
  chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list
  apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false >/dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y gh 2>&1 | tail -2
fi

echo "[hermes-bootstrap] Installing Node.js + agent-browser (browser tool)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi
if ! command -v agent-browser >/dev/null 2>&1; then
  npm install -g agent-browser
fi
if ! command -v codex >/dev/null 2>&1; then
  npm install -g @openai/codex
fi
# Download Chromium + system deps (idempotent — skips if already installed)
agent-browser install --with-deps || echo "[hermes-bootstrap] WARNING: agent-browser install failed; browser tool will not work until fixed"

echo "[hermes-bootstrap] Adding hermes venv to system PATH"
HERMES_BIN="${HERMES_HOME}/hermes-agent/venv/bin"
cat >"/etc/profile.d/hermes.sh" <<PROFILE
export PATH="${HERMES_BIN}:\$PATH"
PROFILE
chmod +x "/etc/profile.d/hermes.sh"
# Also add to the hermes user's .bashrc for interactive shells
HERMES_BASHRC="${HERMES_HOME}/../.bashrc"
if [[ "${HERMES_USER}" != "root" ]]; then
  HERMES_BASHRC="/home/${HERMES_USER}/.bashrc"
else
  HERMES_BASHRC="/root/.bashrc"
fi
if ! grep -q "${HERMES_BIN}" "${HERMES_BASHRC}" 2>/dev/null; then
  echo "export PATH=\"${HERMES_BIN}:\$PATH\"" >> "${HERMES_BASHRC}"
fi

echo "[hermes-bootstrap] Rendering templates"
export HERMES_HOME
run_as_hermes "cd '${HERMES_HOME}' && HERMES_HOME='${HERMES_HOME}' python3 ./scripts/render_templates.py"

echo "[hermes-bootstrap] Installing cron script"
mkdir -p "${HERMES_HOME}/scripts" "${HERMES_HOME}/cron"
if [[ "${HERMES_USER}" != "root" ]]; then
  chown -R "${HERMES_USER}:${HERMES_USER}" "${HERMES_HOME}/scripts" "${HERMES_HOME}/cron"
fi

if command -v systemctl >/dev/null 2>&1; then
  echo "[hermes-bootstrap] Installing systemd service"
  cat >/etc/systemd/system/hermes-gateway.service <<EOF
[Unit]
Description=Hermes Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${HERMES_USER}
WorkingDirectory=${HERMES_HOME}
Environment=HERMES_HOME=${HERMES_HOME}
EnvironmentFile=${HERMES_HOME}/.env
ExecStart=${HERMES_HOME}/hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  # In TEMPLATE_MODE we install the unit so the golden snapshot has it,
  # but we don't start it (.env has no customer creds yet). first_boot.sh
  # enables+starts the service per customer.
  if [[ "${TEMPLATE_MODE:-false}" == "true" ]]; then
    echo "[hermes-bootstrap] TEMPLATE_MODE — systemd unit installed but not started"
  else
    systemctl enable --now hermes-gateway.service

    echo "[hermes-bootstrap] Waiting for service"
    sleep 5
    systemctl --no-pager --full status hermes-gateway.service
  fi
else
  echo "[hermes-bootstrap] systemctl unavailable; starting Hermes gateway with nohup"
  cat >"${HERMES_HOME}/start-hermes-gateway.sh" <<EOF
#!/usr/bin/env bash
set -a
source "${HERMES_HOME}/.env"
set +a
cd "${HERMES_HOME}"
exec "${HERMES_HOME}/hermes-agent/venv/bin/python" -m hermes_cli.main gateway run --replace
EOF
  chmod +x "${HERMES_HOME}/start-hermes-gateway.sh"
  run_as_hermes "cd '${HERMES_HOME}'; nohup ./start-hermes-gateway.sh > gateway.log 2>&1 & echo \$! > bootstrap_gateway.pid"
  echo "[hermes-bootstrap] Started Hermes gateway pid $(cat "${HERMES_HOME}/bootstrap_gateway.pid" 2>/dev/null || true)"
  sleep 5
  if ! kill -0 "$(cat "${HERMES_HOME}/bootstrap_gateway.pid")" 2>/dev/null; then
    echo "[hermes-bootstrap] Hermes gateway exited during startup"
    tail -100 "${HERMES_HOME}/gateway.log" || true
    exit 1
  fi
fi

echo "[hermes-bootstrap] Tuning filesystem error behavior"
ROOT_DEV=$(findmnt -n -o SOURCE / 2>/dev/null || true)
if [[ -n "${ROOT_DEV}" ]]; then
  tune2fs -e continue "${ROOT_DEV}" 2>/dev/null || true
fi

# Template-mode exit: golden snapshot build wants everything heavy
# (apt, venv, pip, gh, node, codex CLI) baked in, but NOT customer
# crons or the bootstrap-complete callback. Write the sentinel
# build_template_snapshot.py polls for, then bail.
if [[ "${TEMPLATE_MODE:-false}" == "true" ]]; then
  touch "${HERMES_HOME}/.template_ready"
  chown "${HERMES_USER}:${HERMES_USER}" "${HERMES_HOME}/.template_ready" 2>/dev/null || true
  echo "[hermes-bootstrap] TEMPLATE_MODE complete — sentinel written, exiting before per-customer steps"
  exit 0
fi

echo "[hermes-bootstrap] Installing cron jobs"
chmod +x "${HERMES_HOME}/scripts/refresh_github_token.sh" 2>/dev/null || true
# Run codex-cli auth sync once now so codex is logged in when bootstrap completes.
# Safe if Codex isn't connected yet — the script no-ops and returns 0.
run_as_hermes "HERMES_HOME='${HERMES_HOME}' python3 '${HERMES_HOME}/scripts/sync_codex_cli_auth.py'" || true
WATCHDOG_JOB="* * * * * if ! touch /root/.rw_check 2>/dev/null; then mount -o remount,rw / 2>/dev/null; kill \$(cat ${HERMES_HOME}/bootstrap_gateway.pid 2>/dev/null) 2>/dev/null; sleep 1; cd ${HERMES_HOME} && nohup ./start-hermes-gateway.sh > ${HERMES_HOME}/gateway.log 2>&1 & echo \$! > ${HERMES_HOME}/bootstrap_gateway.pid; fi"
# Nightly auto-update. Tracks the DELIBERATE release ref HERMES_DEPLOY_PIN
# (a branch/tag NoDesk advances only after vetting) instead of bare
# origin/main, so an un-vetted push to main no longer reaches the fleet at
# 03:00. The pin is resolved remotely each night (git fetch + reset to
# FETCH_HEAD), so advancing the ref's target rolls the fleet forward without
# reprovisioning. If the pin is unset we fail LOUD and SAFE: log and skip the
# reset rather than silently pulling main.
DEPLOY_PIN="${HERMES_DEPLOY_PIN:-}"
if [[ -n "${DEPLOY_PIN}" ]]; then
  PULL_JOB="0 3 * * * mount -o remount,rw / 2>/dev/null; cd ${HERMES_HOME} && git fetch origin '${DEPLOY_PIN}' && git reset --hard FETCH_HEAD && sudo -u ${HERMES_USER} python3 ./scripts/render_templates.py >> ${HERMES_HOME}/auto-pull.log 2>&1; chown -R ${HERMES_USER}:${HERMES_USER} ${HERMES_HOME}"
else
  PULL_JOB="0 3 * * * echo \"[hermes-pull] \$(date -u): HERMES_DEPLOY_PIN unset; nightly auto-update DISABLED (refusing to reset to origin/main)\" >> ${HERMES_HOME}/auto-pull.log 2>&1"
  echo "[hermes-bootstrap] WARNING: HERMES_DEPLOY_PIN unset; nightly auto-update DISABLED. Set HERMES_DEPLOY_PIN to a deliberate release ref to re-enable."
fi
CODEX_AUTH_JOB="*/55 * * * * HERMES_HOME=${HERMES_HOME} sudo -u ${HERMES_USER} python3 ${HERMES_HOME}/scripts/sync_codex_cli_auth.py >> ${HERMES_HOME}/codex-cli-auth.log 2>&1"
GITHUB_JOB="*/50 * * * * HERMES_HOME=${HERMES_HOME} ${HERMES_HOME}/scripts/refresh_github_token.sh >> ${HERMES_HOME}/github-token-refresh.log 2>&1"
# On a freshly-provisioned VPS there is no existing crontab, so
# `crontab -l` exits 1. With `set -euo pipefail`, that propagated
# through this pipeline and silently killed the script — the
# "Notifying NoDesk" curl below never ran, and agents stayed stuck
# in "bootstrapping" forever. Use `|| true` on the crontab -l/grep
# leg so the merge always produces output, even when both legs find
# nothing.
{
  { crontab -l 2>/dev/null || true; } | grep -v "rw_check\|auto-pull.log\|refresh_github_token\|sync_codex_cli_auth" || true
  echo "$WATCHDOG_JOB"
  echo "$PULL_JOB"
  echo "$GITHUB_JOB"
  echo "$CODEX_AUTH_JOB"
} | crontab -

# Notify NoDesk that bootstrap finished, so it can flip the agent row's
# status from "bootstrapping" to "active". Without this callback, the
# status flag stays stuck and credential_sync silently no-ops for the
# first few minutes after checkout. HERMES_CLIENT_ID was set in env via
# build_bootstrap_env; we use it as both the URL path and the
# X-Hermes-Token header (same self-auth pattern as the github token
# mint endpoint).
echo "[hermes-bootstrap] Notifying NoDesk that bootstrap finished"
if [[ -n "${HERMES_CLIENT_ID:-}" && -n "${NODESK_BASE_URL:-}" ]]; then
  curl -fsS --max-time 15 -X POST \
    -H "X-Hermes-Token: ${HERMES_CLIENT_ID}" \
    "${NODESK_BASE_URL}/api/agent/${HERMES_CLIENT_ID}/bootstrap-complete" \
    || echo "[hermes-bootstrap] WARNING: bootstrap-complete callback failed; admin status will stay 'bootstrapping' until manually flipped"
else
  echo "[hermes-bootstrap] HERMES_CLIENT_ID or NODESK_BASE_URL not set; skipping callback"
fi

echo "[hermes-bootstrap] Complete"
