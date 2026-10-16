#!/usr/bin/env python3
"""Deterministic cost model for the AWS-native consolidation program.

READ-ONLY. Never mutates AWS. Two inputs, both reproducible:

1. A committed Cost Explorer evidence file (default
   `docs/migrations/evidence/cost-explorer-20261014.json`): gross usage by service and usage type,
   plus the credit lines, read with four GetCostAndUsage calls on 2026-10-14. This script makes
   NO Cost Explorer call itself (each one costs $0.01 and CE calls were a September cost driver).
2. Recorded counts (secrets, Lightsail bundles, billed snapshot size), optionally refreshed with
   `--live` using free read-only list/describe calls.

Usage:
    python3 scripts/aws_cost_model.py                       # recorded counts + committed evidence
    python3 scripts/aws_cost_model.py --live                # refresh counts (read-only)
    python3 scripts/aws_cost_model.py --json out.json       # also write the JSON artifact

Rules (from the master task):
  - Every figure is labelled MEASURED, REALISED or POTENTIAL. No POTENTIAL figure is cash.
  - Scheduled-for-deletion secrets are not billed, so they are never a new saving.
  - Historical fixes (the September Cost Explorer call storm) are reported, never re-counted.
  - Lightsail snapshots bill on STORED size (5.3 GB-month measured), not on the 40 GB disk.
  - Credits netted the bill to $0.00 in Aug-Oct 2026. Until credits run out, a saving extends
    the credit runway; it is not a cash saving. Credit balance/expiry is not exposed by the CE
    API: the owner must read it in the Billing console.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REGION = "us-east-1"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs" / "migrations" / "evidence" / "cost-explorer-20261014.json"

# ---- List-price constants (us-east-1, checked 2026-10-14) ----
SECRET_STORAGE_USD_PER_MONTH = 0.40      # per secret per month
SECRET_API_USD_PER_10K_CALLS = 0.05      # per 10,000 API calls
PARAM_STORE_STANDARD_USD = 0.00          # Standard tier: no per-parameter charge
LIGHTSAIL_MICRO_USD = 7.0                # micro_3_0 bundle/month (live get-bundles)
LIGHTSAIL_NANO_USD = 5.0                 # nano_3_0 bundle/month (live get-bundles)
LIGHTSAIL_SNAPSHOT_USD_PER_GB_MONTH = 0.05
CW_ALARM_USD_PER_MONTH = 0.10            # standard-resolution metric alarm
CW_FREE_ALARMS = 10
KMS_CMK_USD_PER_MONTH = 1.00

# ---- Recorded counts (live-verified 2026-10-14) ----
RECORDED = {
    "active_secrets": 19,
    "scheduled_deletion_secrets": 9,
    "reference_active_secrets_20261012": 22,
    "secrets_deleted_20261014": 3,       # force-deleted 2026-10-14 (CloudTrail)
    # Every running Lightsail instance (live 2026-10-15): the Nano serves sip.wecare.digital since
    # the 03:39 UTC cutover; the Micro stays running as the rollback standby until it is deleted.
    "lightsail_bundles": ["micro_3_0", "nano_3_0"],
    "snapshot_billed_gb": 5.3,           # CE USE1-SnapshotUsage, GB-month
    "cloudwatch_alarms": 73,
    "kms_customer_keys": 4,
}

#: Fixed monthly charges: billed in full at the start of the month, so no run-rate scaling.
FIXED_MONTHLY_SERVICES = {"AWS Business Support+"}


def _aws(args: list[str]) -> str:
    return subprocess.run(["aws", *args, "--region", REGION, "--output", "text"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _count_lines(text: str) -> int:
    """Count non-empty whitespace-separated tokens.

    Must not use a server-side ``length(...)`` query here: when ListSecrets
    paginates (the account has >100 secret entries once planned deletions are
    included), the CLI evaluates the query per page and prints one number per
    page, so a scalar ``int()`` sees e.g. ``"50\n22"`` and raises. Counting the
    ARNs the CLI emits across all pages is pagination-safe.
    """
    return len(text.split())


def live_counts() -> dict:
    out = dict(RECORDED)
    try:
        out["active_secrets"] = _count_lines(_aws([
            "secretsmanager", "list-secrets",
            "--query", "SecretList[?DeletedDate==null].ARN"]))
        out["scheduled_deletion_secrets"] = _count_lines(_aws([
            "secretsmanager", "list-secrets", "--include-planned-deletion",
            "--query", "SecretList[?DeletedDate!=null].ARN"]))
        # All instances, not one name: keeps working after the Micro is deleted.
        out["lightsail_bundles"] = sorted(_aws([
            "lightsail", "get-instances", "--query", "instances[].bundleId"]).split())
        # describe-alarms paginates at 50/page, so length(MetricAlarms) prints
        # one number per page (e.g. "50\n22"); count the names across all pages.
        out["cloudwatch_alarms"] = _count_lines(_aws([
            "cloudwatch", "describe-alarms", "--query", "MetricAlarms[].AlarmName"]))
    except (subprocess.CalledProcessError, ValueError) as exc:  # pragma: no cover
        print(f"warning: live pull failed, using recorded counts: {exc}", file=sys.stderr)
    return out


# ── measured baseline from the committed Cost Explorer evidence ─────────────────────────────

def _days(period: dict) -> int:
    from datetime import date
    start = date.fromisoformat(period["start"])
    end = date.fromisoformat(period["end"])
    return (end - start).days


def measured(evidence: dict) -> dict:
    gross = evidence["gross_by_service"]
    sep = gross["2026-09"]["groups"]
    octo = gross["2026-10"]
    oct_days = _days(octo)
    scale = 31 / oct_days
    run_rate = {}
    for service, row in octo["groups"].items():
        usd = row["usd"]
        run_rate[service] = round(usd if service in FIXED_MONTHLY_SERVICES else usd * scale, 2)
    usage = evidence["usage_types_selected_services"]

    def ut(month: str, key: str) -> dict:
        return usage[month]["groups"].get(key, {"usd": 0.0, "quantity": 0.0})

    credits = {m: round(v["groups"].get("Credit", {"usd": 0.0})["usd"], 2)
               for m, v in evidence["record_type"].items()}
    return {
        "gross_total": {m: round(sum(r["usd"] for r in v["groups"].values()), 2)
                        for m, v in gross.items()},
        "credits": credits,
        "oct_days": oct_days,
        "sep_by_service": {k: round(v["usd"], 2) for k, v in sep.items()},
        "oct_run_rate_by_service": run_rate,
        "oct_run_rate_total": round(sum(run_rate.values()), 2),
        "amplify_build_minutes": {"2026-09": ut("2026-09", "USE1-BuildDuration")["quantity"],
                                  "2026-10_mtd": ut("2026-10", "USE1-BuildDuration")["quantity"]},
        "amplify_build_usd": {"2026-09": ut("2026-09", "USE1-BuildDuration")["usd"],
                              "2026-10_run_rate": round(
                                  ut("2026-10", "USE1-BuildDuration")["usd"] * scale, 2)},
        "amplify_egress_gb": {"2026-09": ut("2026-09", "USE1-DataTransferOut")["quantity"],
                              "2026-10_mtd": ut("2026-10", "USE1-DataTransferOut")["quantity"]},
        "amplify_egress_usd": {"2026-09": ut("2026-09", "USE1-DataTransferOut")["usd"],
                               "2026-10_run_rate": round(
                                   ut("2026-10", "USE1-DataTransferOut")["usd"] * scale, 2)},
        "cost_explorer_usd": {"2026-09": round(sep.get("AWS Cost Explorer", {"usd": 0})["usd"], 2),
                              "2026-10_mtd": round(octo["groups"].get(
                                  "AWS Cost Explorer", {"usd": 0})["usd"], 2)},
    }


# ── levers and scenarios ─────────────────────────────────────────────────────────────────────

@dataclass
class Lever:
    name: str
    label: str            # REALISED | POTENTIAL | NOT_A_LEVER | HISTORICAL
    monthly_delta: float  # negative = saving
    decision: str
    notes: list[str] = field(default_factory=list)


def levers(counts: dict, m: dict, *, amplify_build_reduction: float = 0.5,
           secret_candidates: int = 3) -> list[Lever]:
    build_rr = m["amplify_build_usd"]["2026-10_run_rate"]
    egress_rr, egress_sep = (m["amplify_egress_usd"]["2026-10_run_rate"],
                             m["amplify_egress_usd"]["2026-09"])
    alarms = counts["cloudwatch_alarms"]
    snapshot = round(counts["snapshot_billed_gb"] * LIGHTSAIL_SNAPSHOT_USD_PER_GB_MONTH, 2)
    # The Micro -> Nano saving is REALISED only once the Micro stops billing (ROLLBACK.md).
    bundles = counts["lightsail_bundles"]
    on_nano, micro_billing = "nano_3_0" in bundles, "micro_3_0" in bundles
    nano_notes = [f"Snapshot storage ${snapshot:.2f}/mo either way."]
    if on_nano and not micro_billing:
        nano_label, nano_decision = "REALISED", "done: the Nano serves SIP and the Micro is deleted"
    elif on_nano:
        nano_label = "POTENTIAL"
        nano_decision = "cut over 2026-10-15; realised when the Micro rollback standby is deleted"
        nano_notes.insert(0, f"Until then both bill ${LIGHTSAIL_MICRO_USD + LIGHTSAIL_NANO_USD:.2f}"
                             "/mo, prorated hourly.")
    else:
        nano_label, nano_decision = "POTENTIAL", "Nano not built; see lightsail-nano-feasibility.md"
    return [
        Lever("secrets_deleted", "REALISED",
              -round(counts["secrets_deleted_20261014"] * SECRET_STORAGE_USD_PER_MONTH, 2),
              "done 2026-10-14 (force-deleted; no recovery window)",
              ["Counted against the 2026-10-12 reference of "
               f"{counts['reference_active_secrets_20261012']} active secrets."]),
        Lever("support_plan_business_plus", "POTENTIAL",
              -m["oct_run_rate_by_service"].get("AWS Business Support+", 0.0),
              "owner: keep Business Support+ or move to Basic",
              ["Largest single line. Trade-off: loses Business-tier case SLAs and support API."]),
        Lever("amplify_build_minutes", "POTENTIAL", -round(build_rr * amplify_build_reduction, 2),
              "owner: batch merges / skip docs-only builds / pause auto-build",
              [f"Sep {m['amplify_build_minutes']['2026-09']:.0f} min "
               f"(${m['amplify_build_usd']['2026-09']:.2f}); Oct run-rate "
               f"${build_rr:.2f}/mo from {m['amplify_build_minutes']['2026-10_mtd']:.0f} min "
               f"in {m['oct_days']} days.",
               f"Assumes a {amplify_build_reduction:.0%} build reduction; every merge to stack "
               "triggers a full build."]),
        Lever("amplify_egress", "POTENTIAL", -round(max(egress_rr - egress_sep, 0.0), 2),
              "investigate the October hosting egress jump before acting",
              [f"Egress {m['amplify_egress_gb']['2026-09']:.1f} GB in Sep vs "
               f"{m['amplify_egress_gb']['2026-10_mtd']:.1f} GB in Oct 1-{m['oct_days']}."]),
        Lever("cloudwatch_alarms", "POTENTIAL", 0.0,
              "review only; no reduction assumed",
              [f"{alarms} alarms: ${max(alarms - CW_FREE_ALARMS, 0) * CW_ALARM_USD_PER_MONTH:.2f}"
               "/mo after the 10 free."]),
        Lever("secrets_consolidation", "POTENTIAL",
              -round(secret_candidates * SECRET_STORAGE_USD_PER_MONTH, 2),
              "owner confirms each candidate in secrets-access-matrix.md",
              [f"{counts['active_secrets']} active secrets = "
               f"${counts['active_secrets'] * SECRET_STORAGE_USD_PER_MONTH:.2f}/mo.",
               f"Up to {secret_candidates} candidates (unreferenced/scripts-only); grouping of "
               "security-sensitive secrets is not proposed."]),
        Lever("kms_customer_keys", "NOT_A_LEVER", 0.0, "keep",
              [f"{counts['kms_customer_keys']} CMKs = "
               f"${counts['kms_customer_keys'] * KMS_CMK_USD_PER_MONTH:.2f}/mo; one protects 6 "
               "secrets, the other three were not usage-audited here."]),
        Lever("lightsail_nano", nano_label, -(LIGHTSAIL_MICRO_USD - LIGHTSAIL_NANO_USD),
              nano_decision, nano_notes),
        Lever("lightsail_retire", "POTENTIAL",
              -(LIGHTSAIL_NANO_USD if on_nano else LIGHTSAIL_MICRO_USD),
              "not authorised: needs an approved SIP media replacement first",
              [f"Snapshot retention would remain ${snapshot:.2f}/mo if kept."]),
        Lever("cost_explorer_calls", "HISTORICAL", 0.0, "already fixed; not counted again",
              [f"Sep ${m['cost_explorer_usd']['2026-09']:.2f} -> Oct "
               f"${m['cost_explorer_usd']['2026-10_mtd']:.2f} month to date."]),
    ]


def payback_months(one_time_usd: float, monthly_saving: float) -> float | None:
    return None if monthly_saving <= 0 else round(one_time_usd / monthly_saving, 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="refresh counts (read-only)")
    ap.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    ap.add_argument("--json", metavar="PATH", help="write JSON artifact")
    ap.add_argument("--amplify-build-reduction", type=float, default=0.5)
    ap.add_argument("--secret-candidates", type=int, default=3)
    args = ap.parse_args(argv)

    counts = live_counts() if args.live else dict(RECORDED)
    m = measured(json.loads(args.evidence.read_text(encoding="utf-8")))
    ls = levers(counts, m, amplify_build_reduction=args.amplify_build_reduction,
                secret_candidates=args.secret_candidates)

    print(f"\nAWS cost model (region {REGION}; {'LIVE' if args.live else 'recorded'} counts; "
          f"evidence {args.evidence.name})")
    print("=" * 78)
    print("MEASURED gross usage (credits excluded):")
    for month, total in m["gross_total"].items():
        print(f"  {month}: ${total:>7.2f}   credits ${m['credits'].get(month, 0.0):>8.2f}")
    print(f"  October run-rate (fixed lines as billed, usage x31/{m['oct_days']}): "
          f"${m['oct_run_rate_total']:.2f}/mo")
    print("\nLevers (negative = monthly reduction):")
    print(f"  {'lever':<28}{'label':<13}{'delta/mo':>9}  decision")
    for lv in ls:
        print(f"  {lv.name:<28}{lv.label:<13}{lv.monthly_delta:>9.2f}  {lv.decision}")
        for n in lv.notes:
            print(f"      - {n}")
    potential = round(sum(lv.monthly_delta for lv in ls
                          if lv.label == "POTENTIAL" and lv.name not in {"lightsail_retire"}), 2)
    print(f"\n  Sum of POTENTIAL levers excluding Lightsail retirement: ${potential:.2f}/mo")
    print(f"  Lightsail nano payback on a $5 overlap alone: "
          f"{payback_months(LIGHTSAIL_NANO_USD, 2.0)} months (engineering time excluded)")
    print("\nCash note: credits covered 100% of gross usage in Aug-Oct 2026, so none of these is "
          "a cash saving\nuntil the credits are exhausted. Check the balance and expiry in Billing.")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "region": REGION, "counts": counts, "measured": m,
            "levers": [asdict(lv) for lv in ls],
            "potential_total_excluding_retirement": potential,
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
