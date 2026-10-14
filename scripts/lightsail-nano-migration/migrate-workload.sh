#!/usr/bin/env bash
# migrate-workload.sh — copy Asterisk/SIP config, certificates and IVR prompts from the
# production micro to the fresh nano, with checksums. Dry-run by default.
#
# Secrets are never embedded or printed. Files stream prod -> nano through the operator's own
# SSH sessions (`ssh prod tar | ssh nano tar`), so no copy lands on the operator's disk.
#
# Usage:
#   Preview transfer:  ./migrate-workload.sh
#   Transfer:          APPLY=1 CONFIRM=I-APPROVE-migrate ./migrate-workload.sh
#   Preview cutover:   ./migrate-workload.sh --cutover
#   Cutover (IP move): APPLY=1 CONFIRM=I-APPROVE-cutover PRECUTOVER_VERIFIED=1 \
#                        ./migrate-workload.sh --cutover
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh
CUTOVER=0; [ "${1:-}" = "--cutover" ] && CUTOVER=1
verify_context
SSH_USER="${SSH_USER:-ec2-user}"
PROD_IP="$(instance_ip "${PROD_INSTANCE}")"
NANO_IP="$(instance_ip "${NANO_INSTANCE}")"
log "prod=${PROD_IP}  nano=${NANO_IP}"

# Standard Asterisk + Let's Encrypt layout, relative to /. Confirm on the box with preflight.sh.
PATHS="etc/asterisk etc/letsencrypt var/lib/asterisk/sounds/custom"

tree_digest() {
  # One digest over (path, sha256) of every file under PATHS. Prints only the digest.
  "${SSH_BIN}" "${SSH_USER}@$1" \
    "cd / && sudo find ${PATHS} -type f -exec sha256sum {} + 2>/dev/null | sort -k2 | sha256sum | cut -d' ' -f1"
}

asterisk_version() {
  "${SSH_BIN}" "${SSH_USER}@$1" "asterisk -V 2>/dev/null || echo absent"
}

if [ "${CUTOVER}" = "0" ]; then
  log "=== WORKLOAD TRANSFER (no IP move) ==="
  if [ "${DRYRUN}" = "1" ]; then
    log "DRY-RUN would: require nano Asterisk version == prod Asterisk version"
    log "DRY-RUN would: stream /{${PATHS// /,}} prod -> nano with ssh|tar (permissions kept)"
    log "DRY-RUN would: compare a sha256 tree digest on both hosts and stop on mismatch"
    log "DRY-RUN would: create a 1G swapfile on the nano only if no swap exists"
    exit 0
  fi
  require_approval "migrate"
  require_recovery_snapshot
  [ "${PROD_IP}" != "UNKNOWN" ] && [ "${NANO_IP}" != "UNKNOWN" ] || die "instance IPs unknown"
  [ "${PROD_IP}" != "${NANO_IP}" ] || die "prod and nano resolve to the same IP; refusing"
  prod_v="$(asterisk_version "${PROD_IP}")"; nano_v="$(asterisk_version "${NANO_IP}")"
  [ "${nano_v}" != "absent" ] || die "Asterisk is not installed on the nano (AL2023 has no package; build ${prod_v})"
  [ "${prod_v}" = "${nano_v}" ] || die "Asterisk version mismatch: prod '${prod_v}' vs nano '${nano_v}'"
  src="$(tree_digest "${PROD_IP}")"
  log "source digest ${src}"
  "${SSH_BIN}" "${SSH_USER}@${PROD_IP}" "cd / && sudo tar -cpzf - ${PATHS}" \
    | "${SSH_BIN}" "${SSH_USER}@${NANO_IP}" "cd / && sudo tar -xpzf -"
  dst="$(tree_digest "${NANO_IP}")"
  log "destination digest ${dst}"
  [ -n "${src}" ] && [ "${src}" = "${dst}" ] || die "checksum mismatch after transfer; do not cut over"
  "${SSH_BIN}" "${SSH_USER}@${NANO_IP}" \
    "swapon --show | grep -q . || (sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile)"
  "${SSH_BIN}" "${SSH_USER}@${NANO_IP}" "sudo systemctl restart asterisk && systemctl is-active asterisk"
  log "transfer verified. Next: ./verify-nano.sh --pre-cutover, then approved test calls."
  exit 0
fi

log "=== CUTOVER: move static IP ${STATIC_IP_NAME} to ${NANO_INSTANCE} ==="
log "This repoints ${SIP_HOST} traffic. Owner-approved, with a verified rollback (rollback.sh)."
if [ "${DRYRUN}" != "1" ]; then
  require_approval "cutover"
  require_recovery_snapshot
  [ "${PRECUTOVER_VERIFIED:-0}" = "1" ] || die "run ./verify-nano.sh --pre-cutover and an approved test call first, then set PRECUTOVER_VERIFIED=1"
fi
run "detach static IP from the prod micro" -- \
  awsr lightsail detach-static-ip --static-ip-name "${STATIC_IP_NAME}"
run "attach static IP to the nano" -- \
  awsr lightsail attach-static-ip --static-ip-name "${STATIC_IP_NAME}" --instance-name "${NANO_INSTANCE}"
log "Keep the micro RUNNING for rollback. Run ./verify-nano.sh and place an approved real call."
