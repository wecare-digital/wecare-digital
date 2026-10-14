# Lightsail Micro→Nano feasibility

Instance `wecare-voice-bot` · us-east-1a · Amazon Linux 2023 · `micro_3_0` (1 GB RAM, 2 vCPU,
40 GB) · running since 2026-03-18 · static IP `52.3.44.165` (`wecare-static-ip`, attached) ·
recovery snapshot `wecare-voice-bot-backup-20261007` (available, from `micro_3_0`).
Bundle prices from live `get-bundles`: `micro_3_0` $7/mo, `nano_3_0` $5/mo (0.5 GB, 2 vCPU,
20 GB, 1 TB transfer).

## Verdict: NO-GO — keep Micro (capacity evidence INCOMPLETE)

Re-measured read-only on 2026-10-14. The decisive input, guest memory under call load, still
cannot be collected from here, so the safe default stands.

## Measured evidence (2026-10-14, read-only)

| Check | Result | Source |
| --- | --- | --- |
| Firewall | tcp 80, 443, 5061 and udp 10000-60000 open to 0.0.0.0/0; tcp 22 and 8899 not open | `get-instance-port-states` |
| SIP/TLS 5061 | reachable; cert CN=`sip.wecare.digital`, Let's Encrypt, valid to 2026-11-18 | `openssl s_client` |
| DNS | `sip.wecare.digital` → `52.3.44.165` | `dig` |
| Cert monitor | `Wecare/SIP CertDaysToExpiry` publishing daily (35 on 10-13); alarm at ≤10 days is OK | CloudWatch |
| SSH 22 / proxy 8899 | not reachable from outside | `nc` |
| CPU (14 days) | avg 0.94%, max 5.36%, burst capacity 100% | `get-instance-metric-data` |
| Status checks (14 days) | 0 failures | same |
| Disk used | about 5.3 GB (snapshot billed at 5.3 GB-month) — fits 20 GB if that holds | Cost Explorer `USE1-SnapshotUsage` |
| Memory, swap, OOM, Asterisk RSS | **UNKNOWN** — no CloudWatch agent, no SSM agent, SSH closed | — |
| Calling traffic | `wecare-whatsapp-calling` 13-35 invocations/day this week (120-355 the week before) | Lambda metrics |

## Workload now on the box

1. **Asterisk serving `sip.wecare.digital`**: the SIP media leg for WhatsApp Calling on both
   WABAs (last recorded Meta calling settings: `sip.wecare.digital:5061`). Still required.
2. **Airtel SMS proxy on :8899**: retired. The firewall port is closed, no Lambda environment
   references the box, and the four Airtel secrets were deleted on 2026-10-14. `preflight.sh`
   reports whether anything still listens locally.
3. Cert renewal plus the daily cert-check call into `wecare-whatsapp-calling`.

Low CPU alone does not justify Nano. Nano halves RAM to 512 MB; Asterisk with TLS, certbot and
the OS can approach that. Without `free -m`, swap and OOM history under real call load the fit
is unproven.

## What would change the verdict

Run `scripts/lightsail-nano-migration/preflight.sh` on the box through an approved access
session (Lightsail browser SSH; port 22 stays closed). Then:

- **GO** if `MemAvailable` stays well above the Asterisk + TLS working set with swap, disk
  fits 20 GB with margin, there is no OOM history, and the installed Asterisk version can be
  reproduced on a fresh AL2023 nano (AL2023 has no Asterisk package).
- **CONDITIONAL GO** if it fits only with swap or trimming.
- **NO-GO** otherwise.

## Retirement option

**Not a retirement candidate today.** Retirement needs the SIP media leg replaced by a
separately approved design and accepted with real calls. No other provider is assumed
authorised here.

## Cost (from `scripts/aws_cost_model.py`)

| Option | Monthly | Notes |
| --- | --- | --- |
| Keep Micro | $7.00 + $0.27 snapshot | current |
| Fresh Nano after cutover | $5.00 + $0.27 | −$2.00 POTENTIAL; +$5 one-time for a month of overlap |
| Retire Lightsail | $0 (+$0.27 if the snapshot is kept) | needs an approved replacement first |

A $2/month delta does not justify migration risk on a live calling path until the memory
evidence exists. The saving is not realised until the Micro stops billing.

The scripts in `scripts/lightsail-nano-migration/` were repaired on 2026-10-14: `APPLY=1`
previously never left dry-run, the remote-to-remote `rsync` could not run, checksums were never
compared, and there was no rollback script. `tests/test_lightsail_nano_scripts.py` now covers
the gates against a stub AWS CLI.
