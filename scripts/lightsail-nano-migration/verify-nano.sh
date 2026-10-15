#!/usr/bin/env bash
# verify-nano.sh — passive verification. Read-only: places no call, prints no secret.
#
#   ./verify-nano.sh --pre-cutover   probe the nano on its OWN public IP (before the IP move)
#   ./verify-nano.sh                 probe whatever the static IP is attached to (after cutover
#                                    or after rollback)
set -euo pipefail
cd "$(dirname "$0")"; . ./_common.sh
verify_context
if [ "${1:-}" = "--pre-cutover" ]; then
  TARGET_IP="$(instance_ip "${NANO_INSTANCE}")"
else
  TARGET_IP="$(awsr lightsail get-static-ip --static-ip-name "${STATIC_IP_NAME}" \
    --query 'staticIp.ipAddress' --output text 2>/dev/null || echo UNKNOWN)"
fi
[ "${TARGET_IP}" != "UNKNOWN" ] || die "could not resolve the target IP"
log "verifying target ${TARGET_IP}"
FAIL=0
echo "--- SIP/TLS 5061 reachable? ---"
if nc -z -G 5 "${TARGET_IP}" 5061 2>/dev/null || nc -z -w 5 "${TARGET_IP}" 5061 2>/dev/null; then
  echo "5061 OPEN"
else
  echo "5061 CLOSED"; FAIL=1
fi
echo "--- TLS certificate on 5061 (subject and expiry only) ---"
cert="$(tls_subject_dates "${TARGET_IP}")"; echo "${cert}"
printf '%s' "${cert}" | grep -q "CN *= *${SIP_HOST}" || { echo "certificate CN is not ${SIP_HOST}"; FAIL=1; }
echo "--- static IP attachment ---"
awsr lightsail get-static-ip --static-ip-name "${STATIC_IP_NAME}" \
  --query 'staticIp.[ipAddress,isAttached,attachedTo]' --output text
if [ "${1:-}" != "--pre-cutover" ]; then
  echo "--- DNS ---"
  resolved="$(dig +short "${SIP_HOST}" A 2>/dev/null | tail -1)"
  echo "${SIP_HOST} -> ${resolved:-unresolved}"
  [ "${resolved}" = "${TARGET_IP}" ] || { echo "DNS does not point at the static IP"; FAIL=1; }
fi
echo "ACCEPTANCE (manual, cannot self-certify): an approved real WhatsApp call with audio both"
echo "ways, IVR prompts heard, and the post-call callback logged by wecare-whatsapp-calling."
[ "${FAIL}" = "0" ] || die "passive verification failed"
log "passive verification passed"
