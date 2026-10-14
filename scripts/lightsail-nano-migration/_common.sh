#!/usr/bin/env bash
# _common.sh — shared guards for the Lightsail nano migration scripts.
# Sourced by the other scripts. No secrets. Enforces dry-run + account/region.
set -euo pipefail

EXPECTED_ACCOUNT="775261844268"
EXPECTED_REGION="us-east-1"
PROD_INSTANCE="wecare-voice-bot"
NANO_INSTANCE="${NANO_INSTANCE:-wecare-voice-bot-nano}"
STATIC_IP_NAME="wecare-static-ip"
BUNDLE_NANO="nano_3_0"
BLUEPRINT="amazon_linux_2023"

# Dry-run is the DEFAULT. Set APPLY=1 to actually run mutating steps. Even with
# APPLY=1 the scripts refuse any step marked owner-approval without CONFIRM=<token>.
DRYRUN="${APPLY:+}"; DRYRUN="${DRYRUN:-1}"

log()  { printf '[%s] %s\n' "$(date -u +%T)" "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

run() {
  # run <description> -- <command...>
  local desc="$1"; shift; [ "$1" = "--" ] && shift
  if [ "${DRYRUN}" = "1" ]; then
    log "DRY-RUN would: ${desc}"
    printf '         $ %s\n' "$*"
  else
    log "RUN: ${desc}"
    "$@"
  fi
}

verify_context() {
  command -v aws >/dev/null || die "aws CLI not found"
  local acct region
  acct="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
  region="$(aws configure get region 2>/dev/null || echo "$AWS_REGION")"
  [ "$acct" = "$EXPECTED_ACCOUNT" ] || die "wrong account: $acct (expected $EXPECTED_ACCOUNT)"
  log "account OK: $acct"
  log "target region: $EXPECTED_REGION (configured: ${region:-unset})"
}

require_approval() {
  # Owner-approval gate for a production-mutating step.
  local what="$1"
  [ "${CONFIRM:-}" = "I-APPROVE-${what}" ] || die \
    "step '${what}' is production-mutating. Re-run with CONFIRM=I-APPROVE-${what} APPLY=1"
}
