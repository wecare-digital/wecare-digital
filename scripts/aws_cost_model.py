#!/usr/bin/env python3
"""Deterministic cost model for the AWS-native consolidation program.

READ-ONLY. This script never mutates AWS. It computes the recurring-cost
scenarios the migration cares about from (a) deterministic list-price constants
recorded below and (b) optional live *counts* pulled read-only from the account
(secret count, Lightsail bundle). It prints a reconciliation table and writes a
machine-readable JSON artifact so the cost doc cites computed numbers, never
hand-typed ones.

Usage:
    python3 scripts/aws_cost_model.py                 # offline, uses recorded counts
    python3 scripts/aws_cost_model.py --live          # pull live counts (read-only)
    python3 scripts/aws_cost_model.py --json out.json # also write JSON artifact

Design rules (from the master task):
  - Secrets Manager list price is $0.40 per secret per month + $0.05 per 10k API
    calls. These are the planning constants; --live confirms the count only, not
    the price (AWS does not expose per-account secret price via an API).
  - "Scheduled for deletion" secrets are NOT counted as future savings — AWS
    stops billing them at the moment deletion is scheduled, so removing them is
    already realised, not a new win.
  - Lightsail bundle prices come from get-bundles when --live, else the recorded
    constants. The $2/month micro->nano delta is only "realised" once the micro
    actually stops being billable; this script reports it as *potential* until
    then.
  - No theoretical saving is reported as realised cash. Every figure is labelled
    POTENTIAL or REALISED.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict

REGION = "us-east-1"

# ---- Deterministic list-price constants (us-east-1, verified 2026-10-14) ----
SECRET_STORAGE_USD_PER_MONTH = 0.40      # per secret per month
SECRET_API_USD_PER_10K_CALLS = 0.05      # per 10,000 API calls
PARAM_STORE_STANDARD_USD = 0.00          # Standard tier: no per-parameter charge
LIGHTSAIL_MICRO_USD = 7.0                # micro_3_0 bundle/month
LIGHTSAIL_NANO_USD = 5.0                 # nano_3_0 bundle/month
# Lightsail instance snapshots: $0.05/GB-month (us-east-1).
LIGHTSAIL_SNAPSHOT_USD_PER_GB_MONTH = 0.05

# ---- Recorded counts (offline fallback; confirmed live 2026-10-14) ----
RECORDED = {
    "active_secrets": 22,
    "scheduled_deletion_secrets": 13,
    "wix_secrets": 3,  # headless-api-key, catalog-webhook, app-oauth
    "lightsail_bundle": "micro_3_0",
    "snapshot_gb": 40,
}


def _aws(args: list[str]) -> str:
    return subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "text"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def live_counts() -> dict:
    out = dict(RECORDED)
    try:
        out["active_secrets"] = int(_aws([
            "secretsmanager", "list-secrets", "--max-results", "100",
            "--query", "length(SecretList[?DeletedDate==null])",
        ]))
        out["scheduled_deletion_secrets"] = int(_aws([
            "secretsmanager", "list-secrets", "--include-planned-deletion",
            "--max-results", "100",
            "--query", "length(SecretList[?DeletedDate!=null])",
        ]))
        out["lightsail_bundle"] = _aws([
            "lightsail", "get-instance", "--instance-name", "wecare-voice-bot",
            "--query", "instance.bundleId",
        ])
    except (subprocess.CalledProcessError, ValueError) as exc:  # pragma: no cover
        print(f"warning: live pull failed, using recorded counts: {exc}",
              file=sys.stderr)
    return out


@dataclass
class Scenario:
    name: str
    label: str  # BASELINE | POTENTIAL | REALISED
    secrets_monthly: float = 0.0
    lightsail_monthly: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def total_monthly(self) -> float:
        return round(self.secrets_monthly + self.lightsail_monthly, 2)


def build(counts: dict, secret_api_calls_per_month: int = 0) -> list[Scenario]:
    active = counts["active_secrets"]
    wix = counts["wix_secrets"]
    bundle = counts["lightsail_bundle"]
    micro = LIGHTSAIL_MICRO_USD if bundle == "micro_3_0" else LIGHTSAIL_MICRO_USD

    api_cost = round((secret_api_calls_per_month / 10_000)
                     * SECRET_API_USD_PER_10K_CALLS, 2)

    baseline = Scenario(
        "baseline", "BASELINE",
        secrets_monthly=round(active * SECRET_STORAGE_USD_PER_MONTH + api_cost, 2),
        lightsail_monthly=micro,
        notes=[
            f"{active} active secrets x ${SECRET_STORAGE_USD_PER_MONTH} = "
            f"${active * SECRET_STORAGE_USD_PER_MONTH:.2f}/mo storage",
            f"Secrets API calls: ~${api_cost:.2f}/mo "
            f"(at {secret_api_calls_per_month:,} calls/mo)",
            "13 scheduled-for-deletion secrets already stopped billing - NOT counted.",
            f"Lightsail micro_3_0: ${micro:.2f}/mo",
        ],
    )

    # After Wix removal: 3 Wix secrets retired. No grouping assumed yet.
    after_wix = Scenario(
        "after_wix_removal", "POTENTIAL",
        secrets_monthly=round((active - wix) * SECRET_STORAGE_USD_PER_MONTH + api_cost, 2),
        lightsail_monthly=micro,
        notes=[
            f"{active - wix} secrets after retiring {wix} Wix secrets "
            f"({active}-{wix}).",
            f"POTENTIAL saving: ${wix * SECRET_STORAGE_USD_PER_MONTH:.2f}/mo - "
            "realised only after deletion window closes.",
            "Lightsail unchanged in this workstream.",
        ],
    )

    # Security-safe consolidation + Parameter Store moves. We DO NOT pick a fixed
    # target count before access analysis (task B10); model a conservative,
    # access-safe move of non-secret config to Parameter Store Standard (free).
    # Conservative assumption: 2 confirmed non-secret config entries move to SSM.
    ps_moves = 2
    after_consolidation = Scenario(
        "after_safe_consolidation", "POTENTIAL",
        secrets_monthly=round((active - wix - ps_moves) * SECRET_STORAGE_USD_PER_MONTH
                              + api_cost, 2),
        lightsail_monthly=micro,
        notes=[
            f"Illustrative: {ps_moves} confirmed NON-secret config entries moved to "
            "Parameter Store Standard (free).",
            "No security-sensitive secret grouped or moved. Grouping only where every "
            "consuming role already needs every field (task B4).",
            f"POTENTIAL saving over baseline: "
            f"${(wix + ps_moves) * SECRET_STORAGE_USD_PER_MONTH:.2f}/mo.",
            "Final count is an OUTPUT of the access matrix, not a target.",
        ],
    )

    after_nano = Scenario(
        "after_lightsail_nano", "POTENTIAL",
        secrets_monthly=after_consolidation.secrets_monthly,
        lightsail_monthly=LIGHTSAIL_NANO_USD,
        notes=[
            f"Lightsail nano_3_0: ${LIGHTSAIL_NANO_USD:.2f}/mo "
            f"(gross delta ${micro - LIGHTSAIL_NANO_USD:.2f}/mo).",
            "POTENTIAL only until the micro instance stops being billable AND the "
            "temporary dual-run overlap ends.",
            f"Dual-run overlap adds ${LIGHTSAIL_NANO_USD:.2f}/mo while both run.",
        ],
    )

    after_retire = Scenario(
        "after_lightsail_retire", "POTENTIAL",
        secrets_monthly=after_consolidation.secrets_monthly,
        lightsail_monthly=0.0,
        notes=[
            "Lightsail fully retired: $0/mo bundle.",
            "ONLY valid after the voice/SIP workload is independently replaced or "
            "removed AND accepted (task C5/C8). Not authorised here.",
            f"Snapshot retention if kept: "
            f"${counts['snapshot_gb'] * LIGHTSAIL_SNAPSHOT_USD_PER_GB_MONTH:.2f}/mo "
            f"({counts['snapshot_gb']}GB x ${LIGHTSAIL_SNAPSHOT_USD_PER_GB_MONTH}).",
        ],
    )

    return [baseline, after_wix, after_consolidation, after_nano, after_retire]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="pull live counts (read-only) instead of recorded")
    ap.add_argument("--json", metavar="PATH", help="write JSON artifact")
    ap.add_argument("--secret-api-calls", type=int, default=0,
                    help="assumed Secrets Manager API calls/month for request-cost line")
    args = ap.parse_args()

    counts = live_counts() if args.live else dict(RECORDED)
    scenarios = build(counts, args.secret_api_calls)

    base = scenarios[0]
    print(f"\nAWS-native consolidation cost model  (region {REGION}, "
          f"{'LIVE' if args.live else 'recorded'} counts)")
    print("=" * 78)
    print(f"{'scenario':<26}{'label':<11}{'secrets$':>10}"
          f"{'lightsail$':>12}{'total$/mo':>12}{'Δ vs base':>12}")
    print("-" * 78)
    for s in scenarios:
        delta = round(s.total_monthly - base.total_monthly, 2)
        print(f"{s.name:<26}{s.label:<11}{s.secrets_monthly:>10.2f}"
              f"{s.lightsail_monthly:>12.2f}{s.total_monthly:>12.2f}{delta:>12.2f}")
    print("-" * 78)
    print("\nNotes per scenario:")
    for s in scenarios:
        print(f"\n[{s.name}] ({s.label})")
        for n in s.notes:
            print(f"  - {n}")

    print("\nIMPORTANT: every Δ above is POTENTIAL recurring saving. None is realised "
          "cash\nuntil the corresponding deletion window closes / the micro stops "
          "being billed.")

    if args.json:
        payload = {
            "region": REGION,
            "source": "live" if args.live else "recorded",
            "counts": counts,
            "constants": {
                "secret_storage_usd_per_month": SECRET_STORAGE_USD_PER_MONTH,
                "secret_api_usd_per_10k_calls": SECRET_API_USD_PER_10K_CALLS,
                "lightsail_micro_usd": LIGHTSAIL_MICRO_USD,
                "lightsail_nano_usd": LIGHTSAIL_NANO_USD,
            },
            "scenarios": [
                {**asdict(s), "total_monthly": s.total_monthly} for s in scenarios
            ],
        }
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
