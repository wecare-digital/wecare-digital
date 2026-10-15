# Lightsail Nano cutover

## State on 2026-10-15 03:25 UTC: Nano built and verified, cutover NOT done

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

## Cutover (🔒 needs owner approval)

1. Pick a quiet moment: `asterisk -rx 'core show channels count'` shows 0 active calls on the Micro.
2. `APPLY=1 CONFIRM=I-APPROVE-cutover PRECUTOVER_VERIFIED=1 ./migrate-workload.sh --cutover`
   stops renewal and the cert check on the Micro, moves `wecare-static-ip` to the Nano (about a
   minute), then starts both timers on the Nano. `sip.wecare.digital` follows the IP; no Meta
   setting, phone number or WABA registration changes.
3. `./verify-nano.sh`: 5061 open, CN `sip.wecare.digital`, DNS equals the static IP.
4. Owner places a real WhatsApp call: two-way audio, IVR prompt heard, call log in
   `wecare-whatsapp-calling`.
5. Keep the Micro running about a week. Then 🔒 delete it; only then is the $2/month saving real.

## Rollback

`APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh` moves the static IP back to the Micro, whose
Asterisk was never changed. Then re-enable the two timers on the Micro (see `ROLLBACK.md`).

## Before deleting the Micro

- The stored AWS keys (`ec2-user` profile = IAM user `asterisk-ivr-service`, and the asterisk
  user's own profile used by `ivr_engine.py` for Lambda, Polly and S3) came across with the copy.
  Lightsail has no instance roles, so keys stay, but rotate them and confirm least privilege.
- `/root/captures/waba-test-5061-20261007.pcap` (459 MB) is only on the Micro. Keep or delete it.
