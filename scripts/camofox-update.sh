#!/usr/bin/env bash
# Weekly Camofox-browser auto-update with tab-creation health-check + rollback.
# The camofox-browser sidecar tracks origin/main of jo-inc/camofox-browser.
# A "healthy" /health is NOT sufficient — the server can be up while the
# browser fails to launch, so we gate the update on a real POST /tabs creating
# a tab, and roll back to the previous commit if it can't.
# Parameterized by HERMES_HOME (default the fleet-standard path); the camofox
# checkout sits beside it at <parent>/camofox-server.
set -uo pipefail
: "${HERMES_HOME:=/home/hermes/.hermes}"
: "${HERMES_USER:=hermes}"
LOG="${HERMES_HOME}/camofox-update.log"
exec >> "$LOG" 2>&1
echo "=== camofox-update $(date -u) ==="
CD="$(dirname "${HERMES_HOME}")/camofox-server"
[ -d "$CD/.git" ] || { echo "no camofox repo at $CD; skip"; exit 0; }
asH(){ runuser -u "${HERMES_USER}" -- bash -lc "$*"; }
PREV=$(asH "git -C $CD rev-parse HEAD")
asH "git -C $CD fetch --quiet origin" || { echo "fetch failed; skip"; exit 0; }
REMOTE=$(asH "git -C $CD rev-parse origin/HEAD 2>/dev/null || git -C $CD rev-parse origin/main")
if [ "$PREV" = "$REMOTE" ]; then echo "up to date ($PREV)"; exit 0; fi
echo "updating $PREV -> $REMOTE"
asH "git -C $CD reset --hard $REMOTE && cd $CD && npm install --no-audit --no-fund && HOME=$(dirname "${HERMES_HOME}") npx --yes camoufox-js fetch" 2>&1 | tail -2
systemctl restart camofox-browser; sleep 8
TID=$(curl -s -m 25 -X POST localhost:9377/tabs -H 'content-type: application/json' -d '{"userId":"hc","sessionKey":"hc"}' | python3 -c "import json,sys;print(json.load(sys.stdin).get('tabId',''))" 2>/dev/null)
if [ -n "$TID" ]; then
  echo "OK updated to $REMOTE (tab health ok: $TID)"
else
  echo "HEALTHCHECK FAILED -> rollback to $PREV"
  asH "git -C $CD reset --hard $PREV && cd $CD && npm install --no-audit --no-fund" 2>&1 | tail -1
  systemctl restart camofox-browser
  echo "rolled back to $PREV"
fi
echo "=== done $(date -u) ==="
