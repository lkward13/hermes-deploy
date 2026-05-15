#!/usr/bin/env bash
# Fetch a fresh GitHub App installation token from the NoDesk gateway and
# export it as GITHUB_TOKEN. Tokens are valid for ~1 hour.
#
# Usage:
#   source ~/.hermes/skills/github/github_auth.sh
#
# Reads from ~/.hermes/.env:
#   GITHUB_TOKEN_ENDPOINT — full URL to mint endpoint
#   HERMES_CLIENT_ID      — client ID used as auth header

if [ -f "$HOME/.hermes/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$HOME/.hermes/.env"
  set +a
fi

if [ -z "${GITHUB_TOKEN_ENDPOINT:-}" ] || [ -z "${HERMES_CLIENT_ID:-}" ]; then
  echo "github_auth: GITHUB_TOKEN_ENDPOINT or HERMES_CLIENT_ID not set in ~/.hermes/.env" >&2
  return 1 2>/dev/null || exit 1
fi

if [ -z "${GITHUB_INSTALLATION_ID:-}" ]; then
  echo "github_auth: no GitHub App installed for this client — install at https://github.com/apps/nodesk-ai-agent" >&2
  return 1 2>/dev/null || exit 1
fi

response=$(curl -fsS -H "X-Hermes-Token: ${HERMES_CLIENT_ID}" "${GITHUB_TOKEN_ENDPOINT}")
token=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

if [ -z "$token" ]; then
  echo "github_auth: failed to mint token (response: $response)" >&2
  return 1 2>/dev/null || exit 1
fi

export GITHUB_TOKEN="$token"
export GH_TOKEN="$token"   # for the gh CLI
echo "GitHub token minted (account: ${GITHUB_ACCOUNT_LOGIN:-unknown}, expires in ~1hr)"
