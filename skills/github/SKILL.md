---
name: github
description: Read, edit, and deploy GitHub repos via the NoDesk GitHub App installation.
version: 1.0.0
author: NoDesk
metadata:
  hermes:
    tags: [GitHub, git, code, deploy, PR, issues]
---

# GitHub

This agent is connected to GitHub via the **NoDesk AI Agent** GitHub App. Authentication is **NOT** done via `gh auth login`, personal access tokens, or `GITHUB_TOKEN` env var. Do not look for those.

Instead, the agent mints short-lived (~1 hour) installation tokens on demand by calling NoDesk's token endpoint.

## How to authenticate

Run `github_auth.sh` to fetch a fresh token and export it as `GITHUB_TOKEN`. Then use `gh` or plain HTTPS git operations as normal.

```bash
source ~/.hermes/skills/github/github_auth.sh
# GITHUB_TOKEN is now set, valid for ~1 hour

# Now you can do anything:
gh repo list
gh issue list --repo lkward13/jshydroseed
gh pr create --title "..." --body "..."
git clone https://x-access-token:${GITHUB_TOKEN}@github.com/lkward13/jshydroseed.git
```

## Repository scope

The installation only has access to the repos the user selected during install. If a command fails with `Resource not accessible by integration`, the user has not granted access to that repo. They can update access at https://github.com/settings/installations.

## Common operations

```bash
# List accessible repos
source ~/.hermes/skills/github/github_auth.sh
gh repo list --limit 50

# Read a file
gh api /repos/{owner}/{repo}/contents/path/to/file.py | jq -r .content | base64 -d

# Create an issue
gh issue create --repo {owner}/{repo} --title "..." --body "..."

# Trigger a workflow / deployment
gh workflow run deploy.yml --repo {owner}/{repo}
```

## Account info

```bash
echo $GITHUB_ACCOUNT_LOGIN   # the connected GitHub user/org
echo $GITHUB_INSTALLATION_ID # the App installation ID (rarely needed)
```
