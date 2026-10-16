#!/usr/bin/env python3
"""Catch the recovery-kit / architecture docs drifting away from the real system.

Why this exists
---------------
`docs/migrations/recovery-kit/README.md` and `docs/migrations/architecture.md`
assert concrete facts about the platform — how many Lambda handlers there are,
which function domains exist, and roughly how many DynamoDB tables and secrets
are live. Those numbers are true on the day they are written and quietly rot
afterwards: someone adds a Lambda, a new domain, or a new provision script and
the "break glass" kit now under-describes the thing it is supposed to let you
rebuild. A recovery runbook that is wrong is worse than one that is missing,
because it is trusted.

This script re-derives those same facts from the source of truth and compares
them to what the docs claim, so drift is reported instead of discovered during
an incident. It is the recovery-kit sibling of `check_data_model_drift.py` and
follows the same contract:

    python scripts/check_recovery_kit_drift.py            # report, always exit 0
    python scripts/check_recovery_kit_drift.py --gate     # non-zero on drift
    python scripts/check_recovery_kit_drift.py --json

What is authoritative vs what is documentation
----------------------------------------------
* HANDLER COUNT and DOMAINS are checked HARD: they come from the committed tree
  (`amplify/functions/**/handler.py` and the directory layout), so they are exact
  and offline, and a mismatch is real drift that must be fixed.
* TABLE and SECRET counts are checked SOFT: the live counts come from the
  committed inventory snapshot `docs/execution/aws-inventory.json`, which itself
  lags the account. The docs deliberately write these as approximate ("~76") and
  tell the reader to trust `aws_account_inventory.py`. So a small difference here
  is a NUDGE to refresh, not a gate failure — only a large divergence is treated
  as drift. This keeps the gate honest: it fails only on things that are both
  knowable offline and wrong.

Exit codes with --gate: 0 clean, 1 drift in a HARD-checked fact, 2 could not
determine (a doc or source file was unreadable).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "amplify" / "functions"
ARCH_DOC = ROOT / "docs" / "migrations" / "architecture.md"
KIT_DOC = ROOT / "docs" / "migrations" / "recovery-kit" / "README.md"
INVENTORY = ROOT / "docs" / "execution" / "aws-inventory.json"

# A directory directly under amplify/functions/ is a "domain", except `shared`
# (a bundled library, not a deployable domain) and dunder/cache dirs.
NON_DOMAIN_DIRS = {"shared", "__pycache__"}

# How far the documented approximate counts may drift from the snapshot before
# it is worth nudging. Chosen loose on purpose: these are "~" figures and the
# snapshot lags the account, so only a real divergence should speak up.
SOFT_TOLERANCE = 5


def live_handler_count() -> int:
    """Exact: every deployable handler in the committed tree."""
    return sum(
        1
        for p in FUNCTIONS.rglob("handler.py")
        if "__pycache__" not in p.parts
    )


def live_domains() -> list[str]:
    """Exact: the function domains, from the directory layout."""
    return sorted(
        d.name
        for d in FUNCTIONS.iterdir()
        if d.is_dir() and d.name not in NON_DOMAIN_DIRS
    )


def inventory_counts() -> dict[str, int | None]:
    """Soft: table/secret counts from the committed inventory snapshot.

    Returns None for a figure the snapshot does not carry, so a missing snapshot
    degrades to "cannot check this one" rather than a false zero.
    """
    out: dict[str, int | None] = {"tables": None, "secrets": None}
    try:
        data = json.loads(INVENTORY.read_text())
    except (OSError, json.JSONDecodeError):
        return out

    found: dict[str, int] = {}

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                if isinstance(v, int):
                    if kl == "tables":
                        found["tables"] = v
                    elif kl == "secrets":
                        found["secrets"] = v
                elif isinstance(v, list):
                    if kl == "tables" and "tables" not in found:
                        found["tables"] = len(v)
                    elif kl == "secrets" and "secrets" not in found:
                        found["secrets"] = len(v)
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    out.update({k: found.get(k) for k in out})
    return out


def doc_claimed_handler_count(text: str) -> int | None:
    """Largest 'N Lambda(s)/handler(s)' or '~N Python Lambdas' the docs assert."""
    nums = [
        int(m)
        for m in re.findall(
            r"~?(\d{2,3})\s+(?:Python\s+)?(?:Lambda|handler)", text
        )
    ]
    return max(nums) if nums else None


def doc_claimed_domain_count(text: str) -> int | None:
    m = re.search(r"(\d{1,2})\s+domains", text)
    return int(m.group(1)) if m else None


def doc_approx(text: str, noun: str) -> int | None:
    """Pull an approximate '~N <noun>' figure, e.g. '~76 ... tables'."""
    m = re.search(rf"~(\d{{1,4}})\s+(?:live\s+)?{noun}", text)
    return int(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gate", action="store_true",
                    help="exit non-zero when a HARD-checked fact has drifted")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        arch = ARCH_DOC.read_text()
        kit = KIT_DOC.read_text()
    except OSError as exc:
        print(f"cannot read a recovery-kit doc: {exc}", file=sys.stderr)
        return 2
    both = arch + "\n" + kit

    handlers_live = live_handler_count()
    domains_live = live_domains()
    inv = inventory_counts()

    handlers_doc = doc_claimed_handler_count(both)
    domains_doc = doc_claimed_domain_count(both)
    tables_doc = doc_approx(both, "tables")
    secrets_doc = doc_approx(both, "secrets")

    hard_drift: list[str] = []
    soft_nudge: list[str] = []

    # HARD: handler count
    if handlers_doc is None:
        hard_drift.append("docs assert no Lambda/handler count at all")
    elif handlers_doc != handlers_live:
        hard_drift.append(
            f"handler count: docs say {handlers_doc}, tree has {handlers_live}"
        )

    # HARD: domain count (the list is exact; the docs cite the count)
    if domains_doc is not None and domains_doc != len(domains_live):
        hard_drift.append(
            f"domain count: docs say {domains_doc}, tree has "
            f"{len(domains_live)} ({', '.join(domains_live)})"
        )

    # SOFT: table / secret approximations vs the (lagging) snapshot
    for noun, doc_val, live_val in (
        ("tables", tables_doc, inv["tables"]),
        ("secrets", secrets_doc, inv["secrets"]),
    ):
        if doc_val is not None and live_val is not None:
            if abs(doc_val - live_val) > SOFT_TOLERANCE:
                soft_nudge.append(
                    f"{noun}: docs say ~{doc_val}, snapshot has {live_val} "
                    f"(diff > {SOFT_TOLERANCE}) — refresh the inventory and the docs"
                )

    result = {
        "handlers_live": handlers_live,
        "handlers_doc": handlers_doc,
        "domains_live": domains_live,
        "domains_doc": domains_doc,
        "tables_doc": tables_doc,
        "tables_snapshot": inv["tables"],
        "secrets_doc": secrets_doc,
        "secrets_snapshot": inv["secrets"],
        "hard_drift": hard_drift,
        "soft_nudge": soft_nudge,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Recovery-kit drift check")
        print(f"  handlers : docs={handlers_doc}  tree={handlers_live}")
        print(f"  domains  : docs={domains_doc}  tree={len(domains_live)}  "
              f"[{', '.join(domains_live)}]")
        print(f"  tables   : docs=~{tables_doc}  snapshot={inv['tables']}")
        print(f"  secrets  : docs=~{secrets_doc}  snapshot={inv['secrets']}")
        if hard_drift:
            print("\n  DRIFT (fix the docs):")
            for d in hard_drift:
                print(f"    - {d}")
        if soft_nudge:
            print("\n  nudge (refresh when convenient):")
            for n in soft_nudge:
                print(f"    - {n}")
        if not hard_drift and not soft_nudge:
            print("\n  clean — docs match the source.")

    if args.gate and hard_drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
