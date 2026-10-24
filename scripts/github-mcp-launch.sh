#!/bin/sh
# Launch github/github-mcp-server over stdio for Kiro.
#
# Why a wrapper instead of an `env` block in mcp.json:
#   the server authenticates with GITHUB_PERSONAL_ACCESS_TOKEN, and
#   .kiro/steering/secret-handling.md forbids a credential appearing in a
#   command, in argv, in an environment assignment on a command line, or in a
#   log line. This script resolves the token from gh's keyring entry at process
#   start via command substitution, so the value is never a literal on disk,
#   never in shell history, and never printed. Same lazy-read discipline as the
#   Lambda handlers: fetched when needed, so re-launching picks up a rotation.
#
# Auth source: `gh auth token` (macOS keyring, account wecare-digital).
set -eu

SERVER="${GITHUB_MCP_SERVER_BIN:-/opt/homebrew/bin/github-mcp-server}"

GH="${GH_BIN:-}"
if [ -z "$GH" ]; then
	GH="$(command -v gh 2>/dev/null || true)"
fi
if [ -z "$GH" ] && [ -x "$HOME/bin/gh" ]; then
	GH="$HOME/bin/gh"
fi

if [ ! -x "$SERVER" ]; then
	echo "github-mcp-launch: server not found at $SERVER" >&2
	echo "github-mcp-launch: install it with 'brew install github-mcp-server'" >&2
	exit 127
fi

if [ -z "$GH" ] || [ ! -x "$GH" ]; then
	echo "github-mcp-launch: gh CLI not on PATH, cannot resolve a token" >&2
	exit 127
fi

# Command substitution only. The value is never written, echoed, or logged.
GITHUB_PERSONAL_ACCESS_TOKEN="$("$GH" auth token 2>/dev/null || true)"
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
	echo "github-mcp-launch: gh holds no token for github.com" >&2
	echo "github-mcp-launch: run 'gh auth login' then restart the MCP server" >&2
	exit 78
fi
export GITHUB_PERSONAL_ACCESS_TOKEN

# Toolsets and exclusions live here rather than in mcp.json so the policy and
# the reason for it stay together, committed and reviewable.
#
# Toolsets: the default set (context, copilot, issues, pull_requests, repos,
# users) plus the three this repo actually has surface for - actions (16
# workflows), dependabot, and code_security (CodeQL).
#
# secret_protection is deliberately NOT enabled. A secret scanning alert payload
# carries the detected value itself, so listing alerts would pull a credential
# straight into model context - the exact thing secret-handling.md exists to
# prevent. Read those alerts in the GitHub UI instead.
#
# Excluded tools, and why each one:
#   delete_repository, create_repository, fork_repository
#       irreversible or repo sprawl; neither is a task for an agent here.
#   create_branch
#       git-workflow.md is single-branch: `wecare.digital` only.
#   create_or_update_file, delete_file, push_files
#       remote writes that bypass every local git guard. block-broad-git-staging
#       and the stage-and-commit-in-one-step rule only see shell git, so a commit
#       pushed through the API would route around both.
#   merge_pull_request, update_pull_request_branch
#       writes to the production branch outside the one-committer rule.
#   actions_run_trigger
#       three of the workflows here deploy to production. Deploys go through
#       scripts/deploy_all_lambdas.py, which publishes versions and moves the
#       `live` alias; a workflow fired by hand does not.
TOOLSETS="default,actions,dependabot,code_security"
EXCLUDE="delete_repository,create_repository,fork_repository,create_branch"
EXCLUDE="$EXCLUDE,create_or_update_file,delete_file,push_files"
EXCLUDE="$EXCLUDE,merge_pull_request,update_pull_request_branch,actions_run_trigger"

exec "$SERVER" stdio \
	--toolsets="$TOOLSETS" \
	--exclude-tools="$EXCLUDE" \
	"$@"
