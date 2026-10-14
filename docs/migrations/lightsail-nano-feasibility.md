# Lightsail Micro→Nano feasibility

Instance `wecare-voice-bot` · us-east-1a · Amazon Linux 2023 · `micro_3_0`
(1GB RAM / 2 vCPU / 40GB) · static IP `52.3.44.165` (`wecare-static-ip`,
attached) · snapshot `wecare-voice-bot-backup-20261007` (available, 40GB).
Bundle prices (live `get-bundles`): micro_3_0 **$7/mo**, nano_3_0 **$5/mo**
(0.5GB / 2 vCPU / 20GB).

## Measured evidence (2026-10-14, read-only)

| Check | Result | Source |
|---|---|---|
| SIP/TLS port 5061 | **OPEN** — voice service live | `nc -z 52.3.44.165 5061` |
| SSH port 22 | **closed/filtered, times out** | `nc`/`ssh` BatchMode |
| CPU utilization 14d | avg ≈ **0.94%**, max ≈ **5.36%** | `lightsail get-instance-metric-data CPUUtilization` |
| Memory utilization | **UNKNOWN** — no CloudWatch mem metric, no host access | — |
| Disk utilization | **UNKNOWN** — same | — |
| Swap / OOM history | **UNKNOWN** — no SSM agent, no CWAgent metrics, needs in-guest access | — |

## Final operational verdict: NO-GO TO DOWNSIZE — KEEP MICRO

Reasoning:
- **This is a closed operational decision, not a pending resize.** The existing Micro stays in
  service. A future Nano proposal is a new change and must first collect the guest evidence below.
- CPU head-room is enormous (sub-2%), so vCPU is not the constraint (nano keeps 2
  vCPU anyway).
- **The decisive unknown is RAM.** Nano halves memory to **512MB**. Asterisk with
  TLS (5061) plus certbot renewals and the OS can sit near or above 512MB; without
  `free -m`/swap evidence from the host we cannot prove it fits. **Low CPU alone
  is explicitly insufficient** (task C3).
- **SSH is not reachable from here**, so the required in-guest capacity audit
  (`free -m`, `df -h`, `lsblk`, `vmstat`, `ps`, `systemctl`, `ss`, Asterisk
  status, swap/OOM, cert-renewal config) **could not be collected**. Per task C3,
  the feasibility assessment is **INCOMPLETE** and therefore the safe default is
  **keep Micro**. No SSH key/private access material was fetched during this audit. A future
  downsizing proposal can run `scripts/lightsail-nano-migration/preflight.sh` through an approved
  host-access session before opening a new migration.

## What would upgrade this to GO
Run `preflight.sh` on `wecare-voice-bot` (via the Lightsail browser SSH console,
since 22 is firewalled). If, under real call load:
- `MemAvailable` stays comfortably above the Asterisk+TLS working set with swap
  configured, and
- used disk fits inside 20GB with margin,
then GO. Otherwise CONDITIONAL GO (add swap / trim) or NO-GO.

## Retirement option
Full retirement is only valid once the voice/SIP workload is independently
replaced or removed and accepted. Per `docs/migration-plan.md`, Lightsail
retirement is an *outcome* of removing the Airtel `:8899` proxy (comms Stage 3)
and moving the Meta SIP media leg (comms Stage 7d) — a separate, approved
program. Not authorised here.

## Cost (from `scripts/aws_cost_model.py`)
- Keep Micro: $7/mo.
- Fresh Nano after cutover: $5/mo (gross −$2/mo) — **POTENTIAL only** until the
  Micro stops being billable and the dual-run overlap ends.
- During migration both run: +$5/mo overlap.
- Snapshot retention if kept after retirement: 40GB × $0.05 = $2/mo.
- The $2/mo delta is **not** realised cash until the Micro is deleted.
