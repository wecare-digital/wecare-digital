#!/usr/bin/env bash
# verify-nano.sh — passive verification of the nano after transfer / cutover.
# Read-only. Does NOT place real calls (that is a human step). No secrets printed.
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh
verify_context

TARGET_IP="${1:-$(aws lightsail get-static-ip --region "${EXPECTED_REGION}" \
  --static-ip-name "${STATIC_IP_NAME}" --query 'staticIp.ipAddress' --output text 2>/dev/null)}"
log "verifying target ${TARGET_IP}"

echo "--- SIP/TLS 5061 reachable? ---"
nc -z -w 4 "${TARGET_IP}" 5061 && echo "5061 OPEN" || echo "5061 CLOSED (fail)"

echo "--- TLS handshake on 5061 (cert presence, no secret) ---"
echo | timeout 6 openssl s_client -connect "${TARGET_IP}:5061" 2>/dev/null \
  | openssl x509 -noout -subject -dates 2>/dev/null || echo "  (no TLS cert returned)"

echo "--- static IP attachment ---"
aws lightsail get-static-ip --region "${EXPECTED_REGION}" --static-ip-name "${STATIC_IP_NAME}" \
  --query 'staticIp.{ip:ipAddress,attached:isAttached,to:attachedTo}' --output table

echo "--- nano resource snapshot (CPU; mem/disk need in-guest preflight.sh) ---"
aws lightsail get-instance-metric-data --region "${EXPECTED_REGION}" \
  --instance-name "${NANO_INSTANCE}" --metric-name CPUUtilization \
  --period 3600 --unit Percent --statistics Average Maximum \
  --start-time "$(date -u -v-6H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '6 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --query 'metricData[-3:].{t:timestamp,avg:average,max:maximum}' --output table 2>/dev/null || true

echo "ACCEPTANCE (manual, cannot self-certify): a human places a real WhatsApp call;"
echo "then 'python scripts/test_call_paths.py watch' must show non-empty sipHeaders."
echo "DNS: confirm sip.wecare.digital resolves to the static IP after cutover."
