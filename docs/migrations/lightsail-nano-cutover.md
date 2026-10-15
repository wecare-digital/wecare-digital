# Lightsail Nano cutover

**Status 2026-10-15 11:30 UTC: complete.** `wecare-voice-bot-nano` is the only voice server.
The Micro, its 2026-10-07 snapshot and the old IVR key are deleted, calls are no longer
recorded, and there is no backup of the Nano (owner decision). See
[Accepted and retired](#accepted-and-retired-2026-10-15).

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
and certbot). Logs, Docker, the retired SMS proxy, the disabled bot folders and ffmpeg were left
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

## Accepted and retired (2026-10-15)

- **Owner acceptance, 10:21 UTC.** Two real WhatsApp calls, one to each business number,
  reached the Nano and played the IVR prompt. Both recordings uploaded complete (15.6 s and
  13.1 s, full WAV headers). After each call the Lambda sent the post-call menu text and a
  disconnect SMS. The call to the second number got the text from both numbers, so the test
  produced 3 WhatsApp messages (with 👍 reactions) and 2 SMS.
- **Retired, about 10:30 UTC (owner-approved, no new backup).**
  - 57 recordings from 2026-06 to 2026-10-07 (33 MB) deleted from the Nano. Their other copies
    went with the Micro and the snapshot.
  - Micro `wecare-voice-bot` deleted, with the 459 MB capture file on it. No DNS record, disk or
    alarm referenced it.
  - Snapshot `wecare-voice-bot-backup-20261007` deleted; no Lightsail snapshots remain.
  - Old `asterisk-ivr-service` key (…L4WC) deleted. Its last use was 07:22 UTC, before the
    rotation. The Nano's key (…NPGH) is the only one left.
  - `aws_cost_model.py --live` reports the $2.00/month as REALISED. Lightsail is $5/month with
    no snapshot storage.
- **Call recording stopped, 11:24 UTC (owner decision).** The flow only plays the welcome
  prompt, so a recording held the caller's microphone audio with no purpose and no retention
  rule.
  - The MixMonitor line in `/etc/asterisk/extensions.conf` is commented out and the dialplan
    reloaded. Backup: `extensions.conf.bak.20261015T1124Z`.
  - `/usr/local/bin/wecare-ivr-upload-recording` removed.
  - IAM `IVRAccess` lost its recordings upload statement. Only the TTS cache grant on
    `secure/stack/ivr-cache/` remains.
  - Both test-call recordings deleted from S3 and the Nano; `secure/u/whatsapp/calls/` holds no
    objects, versions or markers.
  - A loopback call through the live flow left no file, the AGI logged `rec=-`, and the Lambda
    received `post_call_sip`.
  - With the Micro gone, access for this change opened port 22 on the Nano for one IP. The host
    key matched the private-network pin, and the port was closed afterwards.

## Still open

1. **No backup.** The IVR script, dialplan, SIP and TLS configuration exist only on the Nano.
   Losing it means rebuilding by hand; `migrate-workload.sh` copied from the Micro and cannot
   run again.
2. **Post-call messages.** Every caller gets the post-call menu text (from both numbers for calls
   to the second number) and a disconnect SMS. The repo's notification rules say the post-call
   SMS should not fire, but the deployed Lambda (2026-10-08) sends it. Owner decision.

## Rollback

None. The Micro and its snapshot are deleted, and `rollback.sh` refuses to run without the
Micro. Restarting recording would need three things back:

- the MixMonitor line with its upload command, from `extensions.conf.bak.20261015T1124Z` on the
  Nano;
- an upload script that MixMonitor runs once the file is closed;
- an IAM `s3:PutObject` grant on `wecare-digital-get/secure/u/whatsapp/calls/*`.

It should also get a retention rule.
