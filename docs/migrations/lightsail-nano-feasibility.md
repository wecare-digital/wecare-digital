# Lightsail Micro→Nano feasibility

Instance `wecare-voice-bot` · us-east-1a · Amazon Linux 2023 · `micro_3_0` (1 GB RAM, 2 vCPU,
40 GB) · up 206 days · static IP `52.3.44.165` (`wecare-static-ip`) · recovery snapshot
`wecare-voice-bot-backup-20261007` (available). Bundle prices from live `get-bundles`:
`micro_3_0` $7/mo, `nano_3_0` $5/mo (0.5 GB, 2 vCPU, 20 GB).

## Verdict: CONDITIONAL GO for a fresh Nano build; NO-GO for copying this box

Measured in-guest on 2026-10-15 through owner-approved sessions (port 22 opened for one IP,
Lightsail short-lived certificate, host key pinned, port closed and keys deleted afterwards).
Redacted raw output: [`evidence/lightsail-preflight-20261015.txt`](evidence/lightsail-preflight-20261015.txt)
and [`evidence/lightsail-cleanup-20261015.txt`](evidence/lightsail-cleanup-20261015.txt).

**Correction (2026-10-15).** The first version of this document called the box "already paging"
because 571 MB sat in swap. `vmstat` shows zero swap-in and zero swap-out, both since boot and in
the live sample, so that swap is idle memory pushed out over 206 days of uptime, not pressure.

| Measurement | Before cleanup | After cleanup | Fresh Nano estimate |
| --- | --- | --- | --- |
| RAM used by processes | 261 MB | **228 MB** | about 200 MB (Asterisk 85 MB + OS) |
| Available | 504 MB | 537 MB | about 250 MB of ~450 MB usable |
| Swap in use (idle pages) | 570 MB | 520 MB | near zero on a fresh boot |
| Swap traffic (`si`/`so`) | 0 / 0 | 0 / 0 | — |
| Disk used | 14 GB of 40 GB | — | under 5 GB for a clean install |
| CPU | load 0.01; 14-day avg 0.94% | — | ample |

A copy of this box would carry its cruft into 512 MB. A fresh build carrying only Asterisk and the
OS plausibly fits with about 45% headroom, so the condition for GO is a tested fresh build, not a copy.

## Cleanup applied 2026-10-15 02:39 UTC (owner-approved)

- `sms-proxy.service` ("Airtel SMS Proxy", Python on `0.0.0.0:8899`): stopped and disabled. No
  Asterisk or AGI file referenced 8899; Airtel is retired and its secrets are deleted.
- Docker and containerd: stopped and disabled. The only container (`wecare-freeswitch`,
  image `safarov/freeswitch:latest`) had exited 6 months ago and nothing else required Docker.
- Result: 33 MB of RAM freed, port 8899 no longer listening, Asterisk active, 5061 serving
  CN=`sip.wecare.digital` (valid to 2026-11-18), firewall unchanged, no calling errors.
- Rollback: `sudo systemctl enable --now sms-proxy.service docker.socket docker.service containerd.service`.
  Packages and the exited container are untouched.

## Options for the voice server

| Option | Monthly cost | Work | Risk | Notes |
| --- | --- | --- | --- | --- |
| A. Keep the cleaned Micro | $7.00 | none | lowest | today's state |
| B. Fresh Nano, scripted Asterisk build (no copy) | $5.00 (+$5 once for overlap) | build Asterisk 22 from source, PJSIP/TLS, certbot, IVR prompts, cert-check cron; real-call tests | medium | static-IP move keeps `sip.wecare.digital`, so Meta settings stay unchanged; main gain is a reproducible build |
| C. Plivo WhatsApp Calling, retire Lightsail | $0 Lightsail + Plivo per-minute charges | link the WABAs to Plivo, rebuild the IVR as Plivo XML on the existing `wecare-plivo-answer` Lambda, repoint Meta calling | highest change, lowest ops | no server to patch; calls cannot be forwarded to PSTN; cost depends on minutes |

Option C replaces the SIP media leg, so it needs its own owner-approved design and real-call
acceptance before any Meta calling setting changes (the 2026-10-07 settings are recorded in
`docs/execution/snapshots/meta-calling-settings-before-plivo-repoint-20261007.json`). Resolve the
duplicate post-call SMS hazard in `docs/current-communications-architecture.md` §10 first.

## Retirement

Lightsail can retire only through option C (or another approved SIP replacement) after
acceptance with real calls. The Micro stays running until then.
