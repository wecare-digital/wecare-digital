#!/usr/bin/env bash
# migrate-workload.sh — copy ONLY the voice bot from the production micro to a fresh nano, with
# checksums. Dry-run by default.
#
# What is copied (measured on the micro 2026-10-15): the source-built Asterisk 22.8.2 binaries,
# modules and its two private libraries, libsrtp2 (not from an RPM), /etc/asterisk, /var/lib/asterisk
# (IVR prompts, the ivr_engine.py AGI, TLS copies), /var/spool/asterisk, the asterisk and
# wecare-cert-check systemd units, the cert-check script, /etc/letsencrypt, the ec2-user AWS profile
# the cert check uses, and the system python site-packages (boto3 for the AGI). What is NOT copied:
# 2.4 GB of logs, Docker/containerd, the retired Airtel proxy, the disabled bot folders, ffmpeg.
#
# Secrets (TLS key, SIP and AWS credentials) stream prod -> nano through the operator's own SSH
# sessions (`ssh prod tar | ssh nano tar`); no copy lands on the operator's disk and nothing is printed.
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

# The voice bot, relative to /.
PATHS="usr/sbin/asterisk usr/sbin/rasterisk usr/sbin/safe_asterisk usr/sbin/astcanary \
usr/sbin/astdb2sqlite3 usr/sbin/astgenkey usr/sbin/autosupport usr/lib/asterisk \
usr/lib/libasteriskpj.so usr/lib/libasteriskpj.so.2 usr/lib/libasteriskssl.so usr/lib/libasteriskssl.so.1 \
usr/lib64/libsrtp2.so.1 etc/asterisk var/lib/asterisk var/spool/asterisk \
etc/systemd/system/asterisk.service etc/systemd/system/wecare-cert-check.service \
etc/systemd/system/wecare-cert-check.timer usr/local/bin/cert_expiry_check.sh etc/letsencrypt \
home/ec2-user/.aws usr/local/lib/python3.9/site-packages"
# RPM runtime dependencies of Asterisk + its modules (ldd -> rpm -qf on the micro), plus sox
# (IVR audio) and certbot (standalone renewal on port 80).
PACKAGES="sox certbot glibc keyutils-libs krb5-libs libcom_err libcurl-minimal libedit libgcc libidn2 \
libnghttp2 libpsl libselinux libstdc++ libunistring libuuid libxcrypt libxml2 ncurses-libs openssl-libs \
pcre2 sqlite-libs xz-libs zlib"
TIMERS="certbot-renew.timer wecare-cert-check.timer"

remote() { "${SSH_BIN}" "${SSH_USER}@$1" "sudo bash -s"; }

tree_digest() {
  # One digest over the sorted per-file sha256 list of every present PATH, plus the file count.
  remote "$1" <<EOF
cd / && P=""; for p in ${PATHS}; do [ -e "\$p" ] || [ -L "\$p" ] && P="\$P \$p"; done
find \$P -type f -print0 2>/dev/null | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16
find \$P -type f 2>/dev/null | wc -l
EOF
}

if [ "${CUTOVER}" = "0" ]; then
  log "=== VOICE BOT COPY (no IP move) ==="
  if [ "${DRYRUN}" = "1" ]; then
    log "DRY-RUN would: prepare the nano (1G disk swapfile, dnf install ${PACKAGES%% *} and runtime libs, asterisk user)"
    log "DRY-RUN would: stream the voice bot paths prod -> nano with ssh|tar (owners and modes kept)"
    log "DRY-RUN would: compare a sha256 tree digest on both hosts and stop on mismatch"
    log "DRY-RUN would: ldconfig, add logrotate, start Asterisk; keep ${TIMERS} OFF until cutover"
    exit 0
  fi
  require_approval "migrate"
  require_recovery_snapshot
  [ "${PROD_IP}" != "UNKNOWN" ] && [ "${NANO_IP}" != "UNKNOWN" ] || die "instance IPs unknown"
  [ "${PROD_IP}" != "${NANO_IP}" ] || die "prod and nano resolve to the same IP; refusing"
  remote "${NANO_IP}" <<EOF
set -e
swapon --show --noheadings | grep -q '^/swapfile' || { fallocate -l 1G /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon --priority 10 /swapfile; echo '/swapfile none swap sw,pri=10 0 0' >> /etc/fstab; }
dnf -y -q install ${PACKAGES} >/dev/null
getent group asterisk >/dev/null || groupadd -r asterisk
id asterisk >/dev/null 2>&1 || useradd -r -g asterisk -d /var/lib/asterisk -s /sbin/nologin asterisk
EOF
  src="$(tree_digest "${PROD_IP}" | tr '\n' ' ')"
  log "source digest/files: ${src}"
  "${SSH_BIN}" "${SSH_USER}@${PROD_IP}" \
    "cd / && P=''; for p in ${PATHS}; do [ -e \"\$p\" ] || [ -L \"\$p\" ] && P=\"\$P \$p\"; done; sudo tar -cpzf - \$P" \
    | "${SSH_BIN}" "${SSH_USER}@${NANO_IP}" "sudo tar -C / -xpzf -"
  dst="$(tree_digest "${NANO_IP}" | tr '\n' ' ')"
  log "destination digest/files: ${dst}"
  [ -n "${src// /}" ] && [ "${src}" = "${dst}" ] || die "checksum mismatch after transfer; do not cut over"
  remote "${NANO_IP}" <<'EOF'
set -e
ldconfig
install -d -o asterisk -g asterisk -m 755 /var/log/asterisk /var/cache/asterisk /var/run/asterisk
chown -R asterisk:asterisk /etc/asterisk /var/lib/asterisk /var/spool/asterisk /usr/lib/asterisk
printf '%s\n' '/var/log/asterisk/messages /var/log/asterisk/full /var/log/asterisk/queue_log {' \
  '    weekly' '    rotate 4' '    missingok' '    notifempty' '    compress' '    delaycompress' \
  '    sharedscripts' '    postrotate' "        /usr/sbin/asterisk -rx 'logger reload' >/dev/null 2>&1 || true" \
  '    endscript' '}' > /etc/logrotate.d/asterisk
systemctl daemon-reload
missing=$({ ldd /usr/sbin/asterisk; for m in /usr/lib/asterisk/modules/*.so; do ldd "$m"; done; } 2>/dev/null | grep -c 'not found' || true)
[ "$missing" = "0" ] || { echo "missing libraries: $missing"; exit 1; }
systemctl disable --now certbot-renew.timer wecare-cert-check.timer >/dev/null 2>&1 || true
systemctl enable --now asterisk
sleep 8; systemctl is-active asterisk
EOF
  log "copy verified. Next: ./verify-nano.sh --pre-cutover, then the approved cutover."
  exit 0
fi

log "=== CUTOVER: move static IP ${STATIC_IP_NAME} to ${NANO_INSTANCE} ==="
log "This repoints ${SIP_HOST} traffic. Owner-approved, with a verified rollback (rollback.sh)."
if [ "${DRYRUN}" != "1" ]; then
  require_approval "cutover"
  require_recovery_snapshot
  [ "${PRECUTOVER_VERIFIED:-0}" = "1" ] || die "run ./verify-nano.sh --pre-cutover and an approved test call first, then set PRECUTOVER_VERIFIED=1"
fi
# Certificate renewal and the daily cert check must have exactly one owner. Stop them on the micro
# while it still has its IP; start them on the nano through the static IP once it is attached.
run "stop certificate renewal and the daily cert check on the micro" -- \
  sh -c "echo 'systemctl disable --now ${TIMERS}' | ${SSH_BIN} ${SSH_USER}@${PROD_IP} 'sudo bash -s'"
run "detach static IP from the prod micro" -- \
  awsr lightsail detach-static-ip --static-ip-name "${STATIC_IP_NAME}"
run "attach static IP to the nano" -- \
  awsr lightsail attach-static-ip --static-ip-name "${STATIC_IP_NAME}" --instance-name "${NANO_INSTANCE}"
STATIC_IP="$(awsr lightsail get-static-ip --static-ip-name "${STATIC_IP_NAME}" \
  --query 'staticIp.ipAddress' --output text 2>/dev/null || echo UNKNOWN)"
run "start certificate renewal and the daily cert check on the nano" -- \
  sh -c "echo 'systemctl enable --now ${TIMERS}' | ${SSH_BIN} ${SSH_USER}@${STATIC_IP} 'sudo bash -s'"
log "Keep the micro RUNNING for rollback. Run ./verify-nano.sh and place an approved real call."
