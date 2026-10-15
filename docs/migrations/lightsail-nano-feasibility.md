# Lightsail Micro→Nano feasibility

Instance `wecare-voice-bot` · us-east-1a · Amazon Linux 2023 · `micro_3_0` (1 GB RAM, 2 vCPU,
40 GB) · up 206 days · static IP `52.3.44.165` (`wecare-static-ip`) · recovery snapshot
`wecare-voice-bot-backup-20261007` (available). Bundle prices from live `get-bundles`:
`micro_3_0` $7/mo, `nano_3_0` $5/mo (0.5 GB, 2 vCPU, 20 GB).

## Verdict: NO-GO — keep Micro (measured 2026-10-15)

The in-guest preflight ran at 2026-10-15 01:00 UTC through an owner-approved access session
(port 22 opened for one IP only, Lightsail short-lived SSH certificate, host key pinned, port
closed and key material deleted afterwards). Raw, redacted output:
[`evidence/lightsail-preflight-20261015.txt`](evidence/lightsail-preflight-20261015.txt).

| Measurement | Micro today | What Nano offers | Fits? |
| --- | --- | --- | --- |
| RAM in use by processes | 273 MB used, 491 MB available of 916 MB | about 450 MB usable of 512 MB | no headroom |
| Swap in use | **571 MB of a 1 GB swapfile** | same swapfile possible | already paging |
| Asterisk resident memory | 85 MB | — | fits on its own |
| Other resident processes | dockerd 22 MB, containerd 13 MB, SSM agent 12 MB, journal 54 MB, Python proxy 9 MB | — | removable in part |
| Disk used | 14 GB of 40 GB | 20 GB | tight (6 GB margin) |
| CPU | load 0.01; 14-day avg 0.94% | 2 vCPU | yes |
| OOM history | none found | — | — |

The box already keeps 571 MB in swap on 1 GB of RAM. Halving RAM would push the live calling
path into heavier paging, so the move is not safe today. Low CPU does not change that.

## Findings from the preflight

1. **The Airtel SMS proxy is still running.** `sms-proxy.service` ("Airtel SMS Proxy") is active
   and a Python process listens on `0.0.0.0:8899`. The Lightsail firewall blocks 8899 from
   outside, the Airtel secrets were deleted on 2026-10-14 and no Lambda references the box, so
   it serves nothing. Stopping and disabling it is a separate approved change.
2. **Docker and containerd run** with no listening service of their own; they hold about 35 MB.
3. **Asterisk 22.8.2**, built from source on 2026-03-22 (no RPM). A Nano would need the same
   build reproduced by hand; Amazon Linux 2023 has no Asterisk package.
4. **Certificates renew automatically:** `certbot-renew.timer` is active (last run 2026-10-14
   18:37 UTC, next 2026-10-15 09:31 UTC); `/etc/letsencrypt/renewal/sip.wecare.digital.conf` exists.
5. **PJSIP endpoints `1001` and `1002`** are configured and currently unavailable (no registered
   softphone), which is expected between calls.
6. The SSM agent is installed and running, but the instance is not registered with Systems
   Manager, so this preflight needed SSH.

## What would make Nano possible later

Remove the dead proxy, Docker and containerd (about 65 MB resident), trim the journal, then
re-measure during real calls. GO only if swap use falls well below 100 MB and `available`
memory stays above roughly 250 MB under load. Even then the saving is $2/month against
rebuilding Asterisk from source on a live calling path.

## Retirement option

Not a retirement candidate: WhatsApp Calling audio for both numbers still terminates on this
Asterisk. Retirement needs a separately approved SIP media replacement accepted with real calls.

## Cost

| Option | Monthly |
| --- | --- |
| Keep Micro | $7.00 + $0.27 snapshot |
| Nano after cutover | $5.00 + $0.27 (−$2.00 POTENTIAL, +$5 one-time overlap) |
| Retire | $0 (+$0.27 if the snapshot is kept), not authorised |
