#!/usr/bin/env bash
# Enable the hermes-agent remote dashboard (v0.16+) on this VPS, fronted by
# Caddy for TLS. Run as root, after credential_sync has populated the
# dashboard vars in .env. Safe to re-run (idempotent).
#
# Inert-by-default contract: nothing in bootstrap.sh / first_boot.sh calls
# this. NoDesk flips a VPS on by SSHing in and running:
#   bash /home/hermes/.hermes/hermes-deploy/scripts/enable_dashboard.sh
#
# Requires in .env:
#   AGENT_DOMAIN                            e.g. acme.agents.nodesk.io (must
#                                           already resolve to this VPS's IP)
#   HERMES_DASHBOARD_BASIC_AUTH_USERNAME
#   HERMES_DASHBOARD_BASIC_AUTH_PASSWORD
#   HERMES_DASHBOARD_BASIC_AUTH_SECRET      session-signing key
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/home/hermes/.hermes}"
HERMES_USER="${HERMES_USER:-hermes}"
DASHBOARD_PORT=9119

set -a
# shellcheck disable=SC1091
source "${HERMES_HOME}/.env"
set +a

for var in AGENT_DOMAIN HERMES_DASHBOARD_BASIC_AUTH_USERNAME HERMES_DASHBOARD_BASIC_AUTH_PASSWORD HERMES_DASHBOARD_BASIC_AUTH_SECRET; do
  if [[ -z "${!var:-}" ]]; then
    echo "[enable-dashboard] ERROR: ${var} is empty in ${HERMES_HOME}/.env — refusing to enable" >&2
    exit 1
  fi
done

echo "[enable-dashboard] Installing hermes-dashboard.service"
cat >/etc/systemd/system/hermes-dashboard.service <<EOF
[Unit]
Description=Hermes Dashboard (remote gateway login)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${HERMES_USER}
WorkingDirectory=${HERMES_HOME}
Environment=HERMES_HOME=${HERMES_HOME}
EnvironmentFile=${HERMES_HOME}/.env
# 0.0.0.0 bind is what engages the dashboard's auth gate — a loopback bind
# runs with NO auth (web_server.py: "host == loopback -> False (no auth)").
# Direct :9119 access is plain HTTP; block it at the Hetzner cloud firewall
# so the only path in is Caddy's TLS on 443.
ExecStart=${HERMES_HOME}/hermes-agent/venv/bin/python -m hermes_cli.main dashboard --host 0.0.0.0 --port ${DASHBOARD_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now hermes-dashboard.service
sleep 5
systemctl is-active hermes-dashboard.service

# The auth gate engages because of the non-loopback bind above; verify it
# actually did before exposing the port through Caddy. An unauthenticated
# dashboard behind public TLS would be full agent takeover.
echo "[enable-dashboard] Verifying auth gate is engaged"
status_json="$(curl -fsS --max-time 10 "http://127.0.0.1:${DASHBOARD_PORT}/api/status")"
echo "${status_json}"
if ! grep -q '"auth_required"[[:space:]]*:[[:space:]]*true' <<<"${status_json}"; then
  echo "[enable-dashboard] ERROR: dashboard reports auth_required != true — stopping service, NOT configuring Caddy" >&2
  systemctl disable --now hermes-dashboard.service
  exit 1
fi

if ! command -v caddy >/dev/null 2>&1; then
  echo "[enable-dashboard] Installing Caddy"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy
fi

echo "[enable-dashboard] Ensuring Caddy site for ${AGENT_DOMAIN}"
# Append (don't clobber): an agent may already front other ports via Caddy
# (e.g. a :8644 webhook site). Add our TLS site only if it isn't there yet.
mkdir -p /etc/caddy
touch /etc/caddy/Caddyfile
if ! grep -qF "${AGENT_DOMAIN}" /etc/caddy/Caddyfile; then
  cat >>/etc/caddy/Caddyfile <<EOF

${AGENT_DOMAIN} {
    reverse_proxy 127.0.0.1:${DASHBOARD_PORT}
}
EOF
fi

systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy
sleep 3
systemctl is-active caddy

echo "[enable-dashboard] Done. Dashboard at https://${AGENT_DOMAIN} (TLS cert issues on first request; DNS must already point here)"
echo "ENABLE_DASHBOARD_DONE"
