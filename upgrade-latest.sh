#!/usr/bin/env bash
# Upgrade only dependencies currently declared in the web root.
# Backend dependencies remain owned by amplify/package.json.
# --plan prints the exact groups without network or file changes.
# No branch creation, force audit, commit, push or deployment.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == "--plan" ]]; then
  node scripts/upgrade-dependencies.mjs
  exit 0
fi
node scripts/upgrade-dependencies.mjs --apply
npm ci
npm run typecheck
npm run build
npm test
printf '%s\n' 'Review the explicit package.json/package-lock.json diff before committing.'
