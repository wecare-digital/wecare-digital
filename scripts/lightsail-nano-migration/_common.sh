#!/usr/bin/env bash
# _common.sh — shared guards for the Lightsail nano migration scripts.
# Sourced by the other scripts. No secrets. Dry-run is the default.
#
#   APPLY=1                      run mutating steps (otherwise every step only prints its plan)
#   CONFIRM=I-APPROVE-<step>     owner approval for a production-mutating step (needs APPLY=1)
#   NANO_INSTANCE=<name>         the NEW instance (default wecare-voice-bot-nano)
#   AWS_BIN / SSH_BIN            override the aws / ssh executables (used by the tests)
set -euo pipefail

EXPECTED_ACCOUNT="775261844268"
EXPECTED_REGION="us-east-1"
PROD_INSTANCE="wecare-voice-bot"
NANO_INSTANCE="${NANO_INSTANCE:-wecare-voice-bot-nano}"
STATIC_IP_NAME="wecare-static-ip"
SIP_HOST="sip.wecare.digital"
BUNDLE_NANO="nano_3_0"
BLUEPRINT="amazon_linux_2023"
RECOVERY_SNAPSHOT="${RECOVERY_SNAPSHOT:-wecare-voice-bot-backup-20261007}"
AWS_BIN="${AWS_BIN:-aws}"
SSH_BIN="${SSH_BIN:-ssh}"

# Dry-run unless APPLY is exactly "1". (The previous `${APPLY:+}` form always produced
# DRYRUN=1, so APPLY=1 silently did nothing.)
if [ "${APPLY:-0}" = "1" ]; then DRYRUN=0; else DRYRUN=1; fi

log()  { printf '[%s] %s\n' "$(date -u +%T)" "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
awsr() { "${AWS_BIN}" --region "${EXPECTED_REGION}" "$@"; }

run() {
  # run <description> -- <command...>   prints in dry-run, executes with APPLY=1
  local desc="$1"; shift; [ "${1:-}" = "--" ] && shift
  if [ "${DRYRUN}" = "1" ]; then
    log "DRY-RUN would: ${desc}"
    printf '         $ %s\n' "$*"
  else
    log "RUN: ${desc}"
    "$@"
  fi
}

validate_names() {
  case "${NANO_INSTANCE}" in
    "${PROD_INSTANCE}") die "NANO_INSTANCE must not be the production instance ${PROD_INSTANCE}" ;;
  esac
  printf '%s' "${NANO_INSTANCE}" | grep -Eq '^[a-z][a-z0-9-]{2,62}$' \
    || die "NANO_INSTANCE '${NANO_INSTANCE}' is not a valid Lightsail instance name"
}

verify_context() {
  command -v "${AWS_BIN}" >/dev/null || die "aws CLI not found"
  local acct
  acct="$("${AWS_BIN}" sts get-caller-identity --query Account --output text 2>/dev/null || true)"
  [ "${acct}" = "${EXPECTED_ACCOUNT}" ] || die "wrong account: '${acct}' (expected ${EXPECTED_ACCOUNT})"
  log "account OK: ${acct}; region pinned to ${EXPECTED_REGION} on every call"
  validate_names
}

require_approval() {
  # Owner-approval gate for a production-mutating step. Only meaningful with APPLY=1.
  local what="$1"
  [ "${CONFIRM:-}" = "I-APPROVE-${what}" ] || die \
    "step '${what}' is production-mutating. Re-run with APPLY=1 CONFIRM=I-APPROVE-${what}"
}

require_recovery_snapshot() {
  # Backup prerequisite: the known-good micro snapshot must exist and be available.
  local state
  state="$(awsr lightsail get-instance-snapshot --instance-snapshot-name "${RECOVERY_SNAPSHOT}" \
    --query 'instanceSnapshot.state' --output text 2>/dev/null || echo missing)"
  [ "${state}" = "available" ] || die "recovery snapshot ${RECOVERY_SNAPSHOT} is '${state}', not available"
  log "recovery snapshot ${RECOVERY_SNAPSHOT}: available"
}

instance_ip() {
  awsr lightsail get-instance --instance-name "$1" \
    --query 'instance.publicIpAddress' --output text 2>/dev/null || echo UNKNOWN
}

tls_subject_dates() {
  # Passive TLS probe. No `timeout` dependency (absent on macOS); s_client exits on EOF.
  openssl s_client -connect "$1:5061" -servername "${SIP_HOST}" </dev/null 2>/dev/null \
    | openssl x509 -noout -subject -enddate 2>/dev/null || echo "no TLS certificate returned"
}
