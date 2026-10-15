#!/usr/bin/env bash
# rollback.sh — undo a cutover by moving the static IP back to the production micro.
#
# The micro is never modified or stopped during the migration, so rollback is one IP move and
# needs no DNS change (sip.wecare.digital resolves to the static IP). Dry-run by default.
#
#   Preview:  ./rollback.sh
#   Apply:    APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh
verify_context
attached="$(awsr lightsail get-static-ip --static-ip-name "${STATIC_IP_NAME}" \
  --query 'staticIp.attachedTo' --output text 2>/dev/null || echo UNKNOWN)"
log "static IP ${STATIC_IP_NAME} currently attached to: ${attached}"
if [ "${attached}" = "${PROD_INSTANCE}" ]; then
  log "already on ${PROD_INSTANCE}; nothing to roll back"
  exit 0
fi
prod_state="$(awsr lightsail get-instance --instance-name "${PROD_INSTANCE}" \
  --query 'instance.state.name' --output text 2>/dev/null || echo missing)"
[ "${prod_state}" = "running" ] || die "${PROD_INSTANCE} is '${prod_state}'; restore it first (ROLLBACK.md, deeper rollback)"
if [ "${DRYRUN}" != "1" ]; then require_approval "rollback"; fi
run "detach static IP from ${attached}" -- \
  awsr lightsail detach-static-ip --static-ip-name "${STATIC_IP_NAME}"
run "attach static IP to ${PROD_INSTANCE}" -- \
  awsr lightsail attach-static-ip --static-ip-name "${STATIC_IP_NAME}" --instance-name "${PROD_INSTANCE}"
log "then run ./verify-nano.sh (it probes whatever the static IP is attached to)"
