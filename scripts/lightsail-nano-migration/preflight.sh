#!/usr/bin/env bash
# preflight.sh — read-only capacity + dependency audit for the Lightsail voice box.
#
# Run this ON the instance wecare-voice-bot (use the Lightsail browser SSH console;
# TCP 22 is firewalled from outside). It collects the evidence the Nano feasibility
# verdict needs and REDACTS secrets. It mutates nothing.
#
# It never prints: private keys, SIP passwords, env-file values, credentials.
set -euo pipefail

REDACT='s/\(secret\|password\|passwd\|token\|apikey\|api_key\|auth\|bind_rtp\|md5\)[[:space:]]*=.*/\1=<redacted>/Ig'

echo "=== preflight: $(date -u +%FT%TZ) host=$(hostname) ==="

echo "--- OS ---"; cat /etc/os-release 2>/dev/null | sed -n '1,3p' || true

echo "--- MEMORY (the decisive metric for Nano 512MB) ---"
free -m || true
echo "swap:"; swapon --show 2>/dev/null || echo "  (no swap configured)"

echo "--- DISK (must fit Nano 20GB) ---"
df -h / 2>/dev/null || true
lsblk 2>/dev/null || true

echo "--- LOAD / VM ---"; uptime || true; vmstat 1 2 2>/dev/null || true

echo "--- TOP MEMORY CONSUMERS (names only, no args that may hold secrets) ---"
ps -eo pid,comm,rss --sort=-rss 2>/dev/null | head -15 || true

echo "--- SERVICES (is this Asterisk + anything else?) ---"
systemctl list-units --type=service --state=running 2>/dev/null \
  | grep -Ei 'asterisk|certbot|nginx|httpd|airtel|proxy|8899' || echo "  (no matching services)"

echo "--- LISTENING SOCKETS (expect 5061 TLS, RTP range; flag :8899 legacy proxy) ---"
ss -tulnp 2>/dev/null | sed "$REDACT" | grep -E ':(5061|5060|8899|10[0-9]{3}|[1-5][0-9]{4})' || true

echo "--- ASTERISK status (read-only) ---"
if command -v asterisk >/dev/null 2>&1; then
  asterisk -rx 'core show version' 2>/dev/null || true
  asterisk -rx 'pjsip show endpoints' 2>/dev/null | sed "$REDACT" | head -20 || true
else echo "  (asterisk CLI not found)"; fi

echo "--- OOM history (did the kernel kill anything? critical for 512MB) ---"
(dmesg 2>/dev/null | grep -i 'killed process\|out of memory' | tail -10) \
  || journalctl -k 2>/dev/null | grep -i 'oom\|killed process' | tail -10 \
  || echo "  (no OOM evidence found / insufficient privilege)"

echo "--- CERT RENEWAL config (presence only, not contents) ---"
ls -l /etc/letsencrypt/renewal/ 2>/dev/null || echo "  (no letsencrypt renewal dir)"
systemctl list-timers 2>/dev/null | grep -i certbot || echo "  (no certbot timer)"

echo "=== VERDICT INPUTS ==="
echo "If 'MemAvailable' comfortably exceeds the Asterisk+TLS working set WITH swap,"
echo "and used disk fits in 20GB with margin, and there is no OOM history: GO."
echo "Otherwise CONDITIONAL GO (add swap/trim) or NO-GO. CPU is already a non-issue."
echo "=== preflight complete ==="
