# Lightsail Nano cutover

## Built 2026-10-15 03:25 UTC; CUT OVER 2026-10-15 03:39 UTC (owner-approved)

| | Micro (production) | Nano (candidate) |
| --- | --- | --- |
| Instance | `wecare-voice-bot`, `micro_3_0` | `wecare-voice-bot-nano`, `nano_3_0`, us-east-1a |
| Public IP | static `52.3.44.165` (`sip.wecare.digital`) | `3.226.248.119` (temporary) |
| Firewall | 80, 443, 5061/tcp; 10000-60000/udp | 80, 5061/tcp; 10000-60000/udp (no SSH) |
| Asterisk | 22.8.2, serving calls | 22.8.2, running, 0 calls, 315 modules |
| TLS on 5061 | CN=`sip.wecare.digital`, to 2026-11-18 | same certificate, same CN |
| Memory | 244 MB used of 916 MB | 171 MB used of 419 MB usable, 237 MB available |
| Swap | 1 GB file | 419 MB zram + 1 GB file |
| Disk | 14 GB used | 2.1 GB used of 20 GB |
| Renewal + cert-check timers | ON | OFF until cutover (one owner at a time) |

**How it was built** (owner-approved): a fresh Amazon Linux 2023 Nano, then only the voice bot was
copied from the Micro: 23 paths, 3,235 files, SHA-256 tree digest `ca06269dcfc864c6` identical on
both sides. Runtime packages came from `dnf` (the same RPM set `ldd` showed on the Micro, plus sox
and certbot). Logs, Docker, the retired Airtel proxy, the disabled bot folders and ffmpeg were left
behind. `ldd` reports 0 missing libraries. Every SSH session opened port 22 for one IP only,
used Lightsail's short-lived certificate, and closed the port afterwards. The Nano's host key, which
Lightsail did not report yet, was pinned only after an internet scan matched a scan made from the
Micro over the private network.

**Found on the Micro:** a `tcpdump` left running since 2026-03-22 had filled the 459 MB RAM-backed
`/tmp` (the earlier "swap in use" reading was mostly this). It was stopped and the capture moved
to `/root/captures` (mode 600). Asterisk logs had grown to 2.4 GB with no rotation; the Nano has a
logrotate rule.

## Cutover result (2026-10-15 03:39 UTC)

- Pre-checks: recovery snapshot available, static IP on the Micro, 0 active calls on the Micro,
  Nano Asterisk active with 5061 listening.
- Renewal and cert-check timers stopped on the Micro, `wecare-static-ip` moved to the Nano in
  8 seconds, timers started on the Nano (next certbot run 2026-10-15 15:42 UTC). The script was
  ready to re-attach the IP to the Micro automatically if the attach had failed.
- `verify-nano.sh` against live: 5061 open, CN `sip.wecare.digital` (to 2026-11-18), static IP
  attached to `wecare-voice-bot-nano`, DNS `sip.wecare.digital` -> `52.3.44.165`.
- Nano after cutover: Asterisk active, 0 calls, 174 MB used of 419 MB, swap 22 MB in use.
  Its log's ERROR lines are one-time "unable to load optional config file" messages from
  modules with no config (the same `/etc/asterisk` as the Micro); no runtime errors.
- `wecare-whatsapp-calling` errors since cutover: 0.
- The Micro keeps running on a new temporary IP (`100.52.177.46`) as the rollback target, its
  Asterisk untouched and its timers off.

## Still to do

1. Owner places one real WhatsApp call: two-way audio, IVR prompt heard, call log in
   `wecare-whatsapp-calling`. (Meta only sends SIP when a customer calls, so this cannot be
   self-tested.)
2. If anything is wrong: `APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh`, then re-enable the
   two timers on the Micro (`ROLLBACK.md`).
3. After about a week clean: 🔒 `aws lightsail delete-instance --instance-name wecare-voice-bot`
   (the 2026-10-07 snapshot remains for deep rollback), then rotate the `asterisk-ivr-service`
   keys now on the Nano, and change `scripts/aws_cost_model.py` to read the Nano bundle.
4. `/root/captures/waba-test-5061-20261007.pcap` (459 MB) exists only on the Micro; it goes with
   the Micro unless the owner wants it kept.

## Rollback

`APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh` moves the static IP back to the Micro. Then
re-enable `certbot-renew.timer` and `wecare-cert-check.timer` on the Micro and disable them on the
Nano (`ROLLBACK.md`).
