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
  rm -rf "${HERMES_HOME:?}"/*
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
run_as_hermes "'${HERMES_HOME}/hermes-agent/venv/bin/python' -m pip install --upgrade pip wheel setuptools"
run_as_hermes "cd '${HERMES_HOME}/hermes-agent' && '${HERMES_HOME}/hermes-agent/venv/bin/pip' install -e ."
run_as_hermes "'${HERMES_HOME}/hermes-agent/venv/bin/pip' install python-dotenv requests python-telegram-bot"

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
  systemctl enable --now hermes-gateway.service

  echo "[hermes-bootstrap] Waiting for service"
  sleep 5
  systemctl --no-pager --full status hermes-gateway.service
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

echo "[hermes-bootstrap] Installing nightly auto-pull cron"
CRON_JOB="0 3 * * * cd ${HERMES_HOME} && git pull origin main --ff-only >> ${HERMES_HOME}/auto-pull.log 2>&1"
(crontab -l 2>/dev/null | grep -v "git pull origin main"; echo "$CRON_JOB") | crontab -

echo "[hermes-bootstrap] Complete"
