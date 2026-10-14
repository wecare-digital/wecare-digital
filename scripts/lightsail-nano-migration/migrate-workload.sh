#!/usr/bin/env bash
# migrate-workload.sh — transfer Asterisk/SIP config, certs and required data from
# the production micro to the fresh nano, with checksums. Dry-run by default.
#
# Secrets are NEVER embedded here. SIP passwords / private keys travel only inside
# the operator's own authenticated SSH/scp session; this script orchestrates, it
# does not read or print them.
#
# Usage:
#   Preview:        ./migrate-workload.sh
#   Transfer:       APPLY=1 CONFIRM=I-APPROVE-migrate ./migrate-workload.sh
#   Cutover (IP):   APPLY=1 CONFIRM=I-APPROVE-cutover  ./migrate-workload.sh --cutover
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh

CUTOVER=0; [ "${1:-}" = "--cutover" ] && CUTOVER=1
verify_context

PROD_IP="$(aws lightsail get-instance --region "${EXPECTED_REGION}" \
  --instance-name "${PROD_INSTANCE}" --query instance.publicIpAddress --output text 2>/dev/null || echo UNKNOWN)"
NANO_IP="$(aws lightsail get-instance --region "${EXPECTED_REGION}" \
  --instance-name "${NANO_INSTANCE}" --query instance.publicIpAddress --output text 2>/dev/null || echo UNKNOWN)"
log "prod=${PROD_IP}  nano=${NANO_IP}"

# Config/data to migrate (paths are the standard Asterisk + letsencrypt layout;
# adjust on the box after preflight.sh confirms them).
PATHS=(
  "/etc/asterisk/"
  "/etc/letsencrypt/"
  "/var/lib/asterisk/sounds/custom/"   # audio prompts / IVR
)

if [ "${CUTOVER}" = "0" ]; then
  log "=== WORKLOAD TRANSFER (no IP move) ==="
  if [ "${DRYRUN}" != "1" ]; then require_approval "migrate"; fi
  for p in "${PATHS[@]}"; do
    run "checksum source ${p} on prod" -- \
      ssh "ec2-user@${PROD_IP}" "find ${p} -type f -exec sha256sum {} + | sort | sha256sum"
    run "rsync ${p} prod -> nano (operator SSH session, secrets stay in transit)" -- \
      rsync -az --delete "ec2-user@${PROD_IP}:${p}" "ec2-user@${NANO_IP}:${p}"
    run "checksum dest ${p} on nano and compare" -- \
      ssh "ec2-user@${NANO_IP}" "find ${p} -type f -exec sha256sum {} + | sort | sha256sum"
  done
  run "install + enable asterisk on nano" -- \
    ssh "ec2-user@${NANO_IP}" "sudo dnf install -y asterisk && sudo systemctl enable --now asterisk"
  run "add 512MB-safe swap on nano (Nano has 512MB RAM)" -- \
    ssh "ec2-user@${NANO_IP}" "sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
  log "transfer complete. Verify with verify-nano.sh BEFORE any cutover."
  exit 0
fi

log "=== CUTOVER: move static IP ${STATIC_IP_NAME} to ${NANO_INSTANCE} ==="
log "THIS repoints sip.wecare.digital traffic. Owner-approved, verified rollback only."
require_approval "cutover"
run "detach static IP from prod micro" -- \
  aws lightsail detach-static-ip --region "${EXPECTED_REGION}" --static-ip-name "${STATIC_IP_NAME}"
run "attach static IP to nano" -- \
  aws lightsail attach-static-ip --region "${EXPECTED_REGION}" \
    --static-ip-name "${STATIC_IP_NAME}" --instance-name "${NANO_INSTANCE}"
log "cutover done. Keep the micro RUNNING for rollback. Run verify-nano.sh and place"
log "a real WhatsApp call. If anything fails, see ROLLBACK.md."
