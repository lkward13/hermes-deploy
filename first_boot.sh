#!/usr/bin/env bash
# Per-customer first-boot script for snapshot-based provisioning.
#
# Runs once per customer on a VPS that was created by cloning the golden
# Hetzner snapshot built by NoDesk's scripts/build_template_snapshot.py.
# The snapshot already contains:
#   - apt packages + Python venv + all pip dependencies
#   - hermes-deploy and hermes-agent git checkouts
#   - gh CLI, Node.js, agent-browser, codex CLI
#   - The /etc/systemd/system/hermes-gateway.service unit (installed but
#     NOT enabled — needs customer .env first)
# So this script's only job is the customer-specific tail of bootstrap.sh:
#   1. Render .env from env vars passed by NoDesk via SSH
#   2. Pull latest hermes-deploy code (snapshot can be a few days old)
#   3. Install per-customer crons (watchdog, daily pull, codex auth refresh,
#      GitHub token refresh)
#   4. Enable + start the hermes-gateway systemd unit
#   5. Call back to NoDesk /api/agent/.../bootstrap-complete
#
# Idempotent: re-running is safe (crontab merge dedupes, systemd enable is a
# no-op if already enabled, callback handles already-active gracefully).

set -euo pipefail

HERMES_USER="${HERMES_USER:-hermes}"
HERMES_HOME="${HERMES_HOME:-/home/${HERMES_USER}/.hermes}"

echo "[first-boot] Starting per-customer setup for HERMES_CLIENT_ID=${HERMES_CLIENT_ID:-unset}"

# Pull latest hermes-deploy in case the snapshot is older than the
# config templates or render_templates.py logic. Cheap on a warm VPS.
echo "[first-boot] Refreshing hermes-deploy code"
cd "${HERMES_HOME}"
sudo -u "${HERMES_USER}" git fetch origin "${HERMES_DEPLOY_REF:-main}" 2>&1 || echo "[first-boot] WARN: git fetch failed (probably first-boot offline); continuing with snapshot version"
sudo -u "${HERMES_USER}" git reset --hard "origin/${HERMES_DEPLOY_REF:-main}" 2>&1 || true

# Render customer-specific values into .env.
# render_templates.py reads env vars (set inline by the calling SSH session)
# and writes .env, SOUL.md, config.yaml, etc. with those values substituted.
echo "[first-boot] Rendering customer templates"
export HERMES_HOME
sudo -u "${HERMES_USER}" HERMES_HOME="${HERMES_HOME}" python3 "${HERMES_HOME}/scripts/render_templates.py"

# Per-customer crontab jobs. Lifted from bootstrap.sh tail, with the
# pipefail-tolerant crontab merge from commit 0f8fa18.
echo "[first-boot] Installing per-customer crontab"
WATCHDOG_JOB="* * * * * if ! touch /root/.rw_check 2>/dev/null; then mount -o remount,rw / 2>/dev/null; systemctl restart hermes-gateway.service 2>/dev/null; fi"
# Nightly auto-update, run AS THE hermes USER. The .hermes git checkout is
# owned by hermes; running git as root (cron's default user) trips git's
# "detected dubious ownership" guard, which silently no-ops the whole job --
# the reason fleet auto-update has been dead since provision. We also source
# .env before render: render_templates.py rewrites .env from .env.template,
# so an env-less render would blank every credential. Tracks the DELIBERATE
# release ref HERMES_DEPLOY_PIN (a branch/tag NoDesk advances only after
# vetting) instead of bare origin/main, resolved remotely each night (fetch +
# reset to FETCH_HEAD). Fail-safe: pin unset => log and skip, never pull main.
# Steps are &&-chained so a mid-run failure leaves prior rendered files intact
# (render writes .env last, from the sourced env).
DEPLOY_PIN="${HERMES_DEPLOY_PIN:-}"
if [[ -n "${DEPLOY_PIN}" ]]; then
  PULL_JOB="0 3 * * * mount -o remount,rw / 2>/dev/null; sudo -u ${HERMES_USER} bash -c 'cd ${HERMES_HOME} && git fetch origin ${DEPLOY_PIN} && git reset --hard FETCH_HEAD && set -a && . ./.env && set +a && python3 ./scripts/render_templates.py --templates-only' >> ${HERMES_HOME}/auto-pull.log 2>&1; chown -R ${HERMES_USER}:${HERMES_USER} ${HERMES_HOME}"
else
  PULL_JOB="0 3 * * * echo \"[hermes-pull] \$(date -u): HERMES_DEPLOY_PIN unset; nightly auto-update DISABLED (refusing to reset to origin/main)\" >> ${HERMES_HOME}/auto-pull.log 2>&1"
  echo "[first-boot] WARNING: HERMES_DEPLOY_PIN unset; nightly auto-update DISABLED. Set HERMES_DEPLOY_PIN to a deliberate release ref to re-enable."
fi
CODEX_AUTH_JOB="*/55 * * * * HERMES_HOME=${HERMES_HOME} sudo -u ${HERMES_USER} python3 ${HERMES_HOME}/scripts/sync_codex_cli_auth.py >> ${HERMES_HOME}/codex-cli-auth.log 2>&1"
GITHUB_JOB="*/50 * * * * HERMES_HOME=${HERMES_HOME} ${HERMES_HOME}/scripts/refresh_github_token.sh >> ${HERMES_HOME}/github-token-refresh.log 2>&1"
{
  { crontab -l 2>/dev/null || true; } | grep -v "rw_check\|auto-pull.log\|refresh_github_token\|sync_codex_cli_auth" || true
  echo "$WATCHDOG_JOB"
  echo "$PULL_JOB"
  echo "$GITHUB_JOB"
  echo "$CODEX_AUTH_JOB"
} | crontab -

# Start the gateway. The systemd unit was installed by bootstrap.sh during
# the snapshot build but never enabled (TEMPLATE_MODE bail). Now that .env
# has customer credentials, light it up.
echo "[first-boot] Starting hermes-gateway"
systemctl enable --now hermes-gateway.service

# Give it a moment to come up; report status for visibility.
sleep 3
systemctl --no-pager --full status hermes-gateway.service | head -20 || true

# Notify NoDesk so the agent's status flips from "bootstrapping" to "active"
# and any post-active flows (welcome message, credential re-sync) fire.
echo "[first-boot] Notifying NoDesk that first-boot finished"
if [[ -n "${HERMES_CLIENT_ID:-}" && -n "${NODESK_BASE_URL:-}" ]]; then
  curl -fsS --max-time 15 -X POST \
    -H "X-Hermes-Token: ${HERMES_CLIENT_ID}" \
    "${NODESK_BASE_URL}/api/agent/${HERMES_CLIENT_ID}/bootstrap-complete" \
    || echo "[first-boot] WARNING: bootstrap-complete callback failed; admin status will stay 'bootstrapping' until re-triggered"
else
  echo "[first-boot] HERMES_CLIENT_ID or NODESK_BASE_URL not set; skipping callback"
fi

echo "[first-boot] Complete"
