#!/usr/bin/env bash
# bootstrap-nano.sh — provision a FRESH nano_3_0 instance for the voice migration.
#
# NEVER touches the production micro. Dry-run by default. Provisioning a billable
# instance is owner-approval-gated, and needs the recovery snapshot to be available.
#
#   Preview:  ./bootstrap-nano.sh
#   Apply:    APPLY=1 CONFIRM=I-APPROVE-provision-nano ./bootstrap-nano.sh
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh
verify_context
log "plan: provision fresh ${NANO_INSTANCE} (${BUNDLE_NANO}, ${BLUEPRINT}) in ${EXPECTED_REGION}a"
log "the production ${PROD_INSTANCE} is NOT modified by this script"
# A larger micro snapshot CANNOT be restored onto a smaller nano bundle, so a clean nano is
# created and the workload is migrated with migrate-workload.sh instead.
if [ "${DRYRUN}" != "1" ]; then
  require_approval "provision-nano"
  require_recovery_snapshot
  existing="$(awsr lightsail get-instance --instance-name "${NANO_INSTANCE}" \
    --query 'instance.state.name' --output text 2>/dev/null || echo absent)"
  [ "${existing}" = "absent" ] || die "${NANO_INSTANCE} already exists (${existing}); not re-creating"
fi
run "create fresh nano instance" -- \
  awsr lightsail create-instances --instance-names "${NANO_INSTANCE}" \
    --availability-zone "${EXPECTED_REGION}a" --blueprint-id "${BLUEPRINT}" \
    --bundle-id "${BUNDLE_NANO}" \
    --tags key=Project,value=WECARE.DIGITAL key=Purpose,value=voice-nano-candidate
# put-instance-public-ports REPLACES the whole rule set, so the Lightsail defaults (22 and 80 open to
# the internet) never linger. 80 is required: certbot renews sip.wecare.digital with the standalone
# authenticator. SSH stays closed; maintenance opens 22 for one IP only and closes it afterwards.
run "set the nano firewall to exactly 80/tcp, 5061/tcp and 10000-60000/udp (no SSH)" -- \
  awsr lightsail put-instance-public-ports --instance-name "${NANO_INSTANCE}" \
    --port-infos fromPort=80,toPort=80,protocol=TCP fromPort=5061,toPort=5061,protocol=TCP \
    fromPort=10000,toPort=60000,protocol=UDP
log "next: run migrate-workload.sh (copies the voice bot only). The static IP is NOT moved here."
