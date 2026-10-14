#!/usr/bin/env bash
# bootstrap-nano.sh — provision a FRESH nano_3_0 instance for voice migration.
#
# NEVER touches the production micro. Dry-run by default. Provisioning a billable
# instance is owner-approval-gated.
#
#   Preview:  ./bootstrap-nano.sh
#   Apply:    CONFIRM=I-APPROVE-provision-nano APPLY=1 ./bootstrap-nano.sh
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh

verify_context

log "plan: provision fresh ${NANO_INSTANCE} (${BUNDLE_NANO}, ${BLUEPRINT}) in ${EXPECTED_REGION}a"
log "the production ${PROD_INSTANCE} is NOT modified by this script"

# A larger micro snapshot CANNOT be restored onto a smaller nano bundle, so we
# create a clean nano and migrate workload with migrate-workload.sh instead.
if [ "${DRYRUN}" != "1" ]; then require_approval "provision-nano"; fi

run "create fresh nano instance" -- \
  aws lightsail create-instances \
    --region "${EXPECTED_REGION}" \
    --instance-names "${NANO_INSTANCE}" \
    --availability-zone "${EXPECTED_REGION}a" \
    --blueprint-id "${BLUEPRINT}" \
    --bundle-id "${BUNDLE_NANO}"

run "open SIP/TLS 5061 (tcp) on the nano firewall" -- \
  aws lightsail open-instance-public-ports --region "${EXPECTED_REGION}" \
    --instance-name "${NANO_INSTANCE}" \
    --port-info fromPort=5061,toPort=5061,protocol=TCP

run "open RTP media range 10000-60000 (udp) on the nano firewall" -- \
  aws lightsail open-instance-public-ports --region "${EXPECTED_REGION}" \
    --instance-name "${NANO_INSTANCE}" \
    --port-info fromPort=10000,toPort=60000,protocol=UDP

log "next: run migrate-workload.sh once the nano is 'running' and SSH-reachable"
log "DO NOT move the static IP yet — that is the cutover step (migrate-workload.sh --cutover)"
