#!/usr/bin/env bash
# hermes-agent auto-updater. Moves the agent checkout to the NEWEST vetted
# nodesk-v* release tag, health-checks the gateway, and rolls back on failure.
#
# Why tags, not main: NoDesk cuts a `nodesk-v*` tag only after vetting a
# release, so tracking the newest such tag means customer agents never run an
# in-progress commit. The agent venv is an EDITABLE install (`pip install -e`),
# so a code-only update is just checkout+restart; pip/web rebuild run ONLY when
# pyproject/requirements or web/ actually changed between the two revisions.
# Rollback is the same in reverse (checkout the prior SHA + restart).
#
# Usage: hermes-update.sh [run|check]   (check = detection only, no changes)
# Parameterized by HERMES_HOME / HERMES_USER (fleet-standard defaults).
set -uo pipefail
: "${HERMES_HOME:=/home/hermes/.hermes}"
: "${HERMES_USER:=hermes}"
MODE="${1:-run}"
A="${HERMES_HOME}/hermes-agent"
LOG="${HERMES_HOME}/hermes-update.log"
# The box runs the agent code as TWO systemd services off the same checkout:
# hermes-gateway (WS RPC) and hermes-dashboard (REST/WS the mobile app uses, on
# :9119). :8644 is Caddy (a reverse proxy that answers 404 even when the agent
# is down) so it is NOT a liveness signal. Restart whichever of these units
# exist, and gate health on systemd-active + the dashboard answering on :9119.
DASH_PORT=9119
ts(){ date -u +'%Y-%m-%dT%H:%M:%SZ'; }
log(){ echo "[$(ts)] $*" >> "$LOG"; }
ghermes(){ sudo -u "${HERMES_USER}" git -C "$A" "$@"; }

# single-runner guard
exec 9>/tmp/hermes-update.lock || true
flock -n 9 || { log "another run in progress; exit"; exit 0; }

[ -d "$A/.git" ] || { log "no hermes-agent checkout at $A; abort"; exit 0; }

# discover which agent services this box actually runs
SERVICES=""
for s in hermes-gateway hermes-dashboard; do
  systemctl cat "$s.service" >/dev/null 2>&1 && SERVICES="${SERVICES} $s"
done

restart_services(){ for s in $SERVICES; do systemctl restart "$s"; done; }

probe(){
  local s
  for s in $SERVICES; do
    [ "$(systemctl is-active "$s" 2>/dev/null)" = active ] || return 1
  done
  # dashboard liveness on its OWN port (not the Caddy proxy) when present
  if echo "$SERVICES" | grep -q hermes-dashboard; then
    [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "localhost:$DASH_PORT/" 2>/dev/null || echo 000)" != 000 ] || return 1
  fi
  return 0
}

OLD=$(ghermes rev-parse HEAD)
OLD_REF=$(ghermes describe --tags --exact-match 2>/dev/null || echo "$OLD")
ghermes fetch --tags --force --quiet origin 2>>"$LOG" || { log "git fetch failed; keeping $OLD_REF"; exit 0; }
LATEST=$(ghermes tag -l 'nodesk-v*' | sort -V | tail -1)
[ -n "$LATEST" ] || { log "no nodesk-v* tags found; keeping $OLD_REF"; exit 0; }
LATEST_SHA=$(ghermes rev-list -n1 "$LATEST")

if [ "$LATEST_SHA" = "$OLD" ]; then
  [ "$MODE" = check ] && echo "current=$OLD_REF latest=$LATEST would_update=no"
  log "[$MODE] already at latest $LATEST ($OLD); no-op"
  exit 0
fi
if [ "$MODE" = check ]; then
  echo "current=$OLD_REF latest=$LATEST would_update=yes"
  log "[check] current=$OLD_REF latest=$LATEST -> would update to $LATEST_SHA"
  exit 0
fi

log "updating $OLD_REF ($OLD) -> $LATEST ($LATEST_SHA)"
DEPS_CHANGED=0
ghermes diff --quiet "$OLD" "$LATEST_SHA" -- pyproject.toml setup.py setup.cfg requirements.txt requirements-web.txt 2>/dev/null || DEPS_CHANGED=1
WEB_CHANGED=0
ghermes diff --quiet "$OLD" "$LATEST_SHA" -- web 2>/dev/null || WEB_CHANGED=1

ghermes checkout --quiet "$LATEST" 2>>"$LOG" || { log "checkout failed; staying on $OLD_REF"; exit 0; }
if [ "$DEPS_CHANGED" = 1 ]; then
  log "deps changed; pip install -e .[web]"
  ( cd "$A" && sudo -u "${HERMES_USER}" "$A/venv/bin/pip" install -q -e '.[web]' ) >>"$LOG" 2>&1 || log "WARN pip install non-zero (continuing to health-check)"
fi
if [ "$WEB_CHANGED" = 1 ]; then
  # Deliberately do NOT run the vite build on a live box: it peaks ~2.3GB and
  # can OOM a small VPS unattended (bootstrap.sh bakes web_dist into the
  # snapshot for exactly this reason). web_dist is gitignored, so the prior
  # built SPA stays in place and keeps serving — only cosmetically stale until
  # the next snapshot rebuild refreshes it. Backend update still applies.
  log "web/ changed but NOT rebuilding on live box (OOM risk); dashboard serves prior web_dist until next snapshot rebuild"
fi
chown -R "${HERMES_USER}:${HERMES_USER}" "$A"
restart_services

ok=0
for i in $(seq 1 12); do sleep 5; if probe; then ok=1; break; fi; done
if [ "$ok" = 1 ]; then
  log "OK updated to $LATEST; services healthy ($SERVICES)"
  exit 0
fi

# ---- rollback ----
log "HEALTH CHECK FAILED on $LATEST; rolling back to $OLD_REF ($OLD)"
ghermes checkout --quiet "$OLD" 2>>"$LOG"
if [ "$DEPS_CHANGED" = 1 ]; then
  ( cd "$A" && sudo -u "${HERMES_USER}" "$A/venv/bin/pip" install -q -e '.[web]' ) >>"$LOG" 2>&1 || log "WARN rollback pip non-zero"
fi
chown -R "${HERMES_USER}:${HERMES_USER}" "$A"
restart_services
rok=0
for i in $(seq 1 12); do sleep 5; if probe; then rok=1; break; fi; done
if [ "$rok" = 1 ]; then log "ROLLBACK OK; back on $OLD_REF and healthy"; else log "ROLLBACK STILL UNHEALTHY on $OLD_REF -- MANUAL ATTENTION NEEDED"; fi
exit 1
