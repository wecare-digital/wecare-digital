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

## Follow-ups done 2026-10-15 07:20–08:00 UTC (owner-requested)

Host access went through the Micro over the private network: port 22 opened on the Micro for one
IP, Lightsail short-lived certificates, the Nano host key re-scanned and matched the earlier pin.
The Nano's firewall was never opened. Both firewalls were re-read afterwards and match the table.

- **Cert check fixed.** The 07:15 UTC run failed on the Nano: `cert_expiry_check.sh` runs as
  `ec2-user` and appends to `/var/log/cert-expiry.log`, which was not copied. File created
  (`ec2-user`, 644); a manual run returned 200 with 34 days and `CertDaysToExpiry` publishes
  again. `migrate-workload.sh` now creates the file.
- **IVR key rotated, first half.** A new `asterisk-ivr-service` key (…NPGH) is in both consumers:
  `/var/lib/asterisk/.aws/credentials` (AGI) and `/home/ec2-user/.aws/credentials` (cert check),
  both now mode 600 (the second was 664). Verified with STS and an end-to-end cert check. The old
  key (…L4WC) stays active only because the Micro still uses it.
- **Certbot.** `certbot renew --dry-run` passed on the Nano (standalone on port 80, no pre/post
  hooks; the deploy hook copies the cert and reloads `res_pjsip`).
- **IVR S3 target moved to `wecare-digital-get`.** The old target, the `app.wecare.digital`
  bucket, was deleted on 2026-09-28, so every upload had failed silently. Now, under the gated
  root: TTS cache `secure/stack/ivr-cache/`, call recordings `secure/u/whatsapp/calls/`.
  `IVR_S3_BUCKET` in `/etc/asterisk/ivr.env` (loaded by `asterisk.service`, so Asterisk was
  restarted at 0 calls) and the defaults in `ivr_engine.py` changed; `recordingUrl` now carries
  the gated key, never a public URL. Backups on the Nano: `*.bak.20261015T075408Z`. IAM
  `IVRAccess` narrowed to Get/Put on the cache and Put-only on recordings (previous document in
  `.scratch/iam-rollback/`). Self-test as the `asterisk` user: cache write/read and recording
  write work; reading a recording, writing to `o/` or elsewhere in `secure/`, listing and
  deleting are all denied; test objects answered 302 at `wecare.digital/get/` and were deleted.
- **Recordings upload after MixMonitor closes the file (08:15 UTC).** Uploading from the `h`
  extension ran while MixMonitor still held the file open: a 6-second test call (temporary
  self-test context, `Milliwatt` tone) uploaded 65,580 of 96,684 bytes with a zero data-size
  WAV header. Now `MixMonitor(...,,/usr/local/bin/wecare-ivr-upload-recording ...)` uploads
  once the file is closed (skips header-only files, logs to the journal as `wecare-ivr-rec`), and
  the AGI only records the gated key as `recordingUrl`. Re-test: the S3 copy matched the finished
  file byte for byte (SHA-256), header complete, 302 at the edge. The self-test context was then
  removed; the live dialplan differs from `extensions.conf.bak.20261015T0815Z` by that one
  MixMonitor line (AGI backup `ivr_engine.py.bak.20261015T0815Z`). All test recordings deleted.
- **Post-call hook proven on the Nano.** A local loopback call (`Local/c2b-sip@whatsapp`, no
  caller number, no Meta leg) ran the `h` extension, uploaded its recording and reached
  `wecare-whatsapp-calling` as `post_call_sip` (`no callerPhone`, so nothing was sent). It is the
  first `post_call_sip` the Lambda has ever logged; the Micro never delivered one (0 in 30 days;
  its verbose logging is off and its AGI log was empty, with `/tmp` full since at least
  2026-10-07). Test recording deleted from S3 and the Nano.

## Still to do

1. Owner places one real WhatsApp call: two-way audio, IVR prompt heard, call log in
   `wecare-whatsapp-calling`. Because the post-call hook now fires, the call should also leave a
   Calls-page breadcrumb, an object in `secure/u/whatsapp/calls/`, and (toggle
   `whatsapp_calling_postcall_wa` is unset, so default on) the post-call menu text to the caller.
   The recording lands in S3 a few seconds after hangup (`journalctl -t wecare-ivr-rec`).
2. If anything is wrong: `APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh`, then re-enable the
   two timers on the Micro (`ROLLBACK.md`). The Micro still has the old IVR config (dead bucket).
3. After about a week clean: 🔒 `aws lightsail delete-instance --instance-name wecare-voice-bot`
   (the 2026-10-07 snapshot remains for deep rollback), then deactivate and delete the old key
   …L4WC. `scripts/aws_cost_model.py --live` then reports the $2.00 as REALISED.
4. `/root/captures/waba-test-5061-20261007.pcap` (459 MB) exists only on the Micro; it goes with
   the Micro unless the owner wants it kept.
5. The 57 recordings made on the Micro (2026-06 to 2026-10-07, 33 MB, now also on the Nano) were
   never uploaded. Backfilling them into `secure/u/whatsapp/calls/` is an owner decision.

## Rollback

`APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh` moves the static IP back to the Micro. Then
re-enable `certbot-renew.timer` and `wecare-cert-check.timer` on the Micro and disable them on the
Nano (`ROLLBACK.md`).
