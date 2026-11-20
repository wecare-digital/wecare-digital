#!/usr/bin/env python3
"""READ-ONLY dry run: which contacts could be cleaned up, and which must be kept.

Governing policy: docs/ops/scoped-whatsapp-contact-payment-retention-2026-11-20.md
Usage notes:      docs/ops/contact-cleanup-dry-run.md

This script NEVER archives, deletes, updates or writes anything in AWS. Every table is wrapped in a
proxy that only allows scan, query and get_item, and the TTL check only calls
describe_time_to_live. Cleanup, if the operator decides to do it, is the existing reversible
Archive in the contacts API, run by the operator with Admin + MFA.

Each contact gets exactly one label, highest precedence first:

  OPERATOR_HOLD                 the operator selected it (id, exact phone, BSUID or merge link)
  FINANCIAL_RETENTION           invoice, order, payment, attempt or payment-related message found
  LEGAL_OR_IDENTITY_LOCK        the contact row is locked
  REVIEW_REQUIRED               anything unknown, unreadable, ambiguous or truncated
  ELIGIBLE_FOR_APPROVED_ACTION  everything was read and nothing protects it

Selection is by identifier only. A display name is never read as a selector, and two contacts
that share a name stay distinct. The selection is supplied at run time (private JSON file or CLI
arguments) and is never stored in this repository.

Exit codes:
  0  report produced, all inventory complete, expectations (if any) met
  2  inventory incomplete (a read failed): nothing is reported as eligible
  3  selection problem or expectation mismatch: nothing is reported as eligible
  64 usage error
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_SHARED = os.path.join(os.path.dirname(_HERE), "amplify", "functions", "shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

# The classifier lives in the shared layer so the contacts Lambda uses the same code.
from lambda_utils.contact_cleanup import *  # noqa: E402,F401,F403
from lambda_utils.contact_cleanup import (  # noqa: E402
    DEFAULT_PREFIX, ELIGIBLE, MESSAGE_TABLES, Selection, TABLE_SUFFIXES, classify,
    load_selection_file, mask_contact_id,
)


# ── Output ───────────────────────────────────────────────────────────────────────────────────


def render_summary(report: Dict[str, Any]) -> str:
    lines: List[str] = [f"Contact cleanup dry run (read-only). Status: {report['status']}"]
    for problem in report.get("problems", []):
        lines.append(f"  PROBLEM: {problem}")
    totals = report.get("totals") or {}
    if totals:
        lines.append(f"Contacts scanned: {totals['contactsScanned']}")
        for label, n in totals["byClassification"].items():
            lines.append(f"  {label}: {n}")
        lines.append(f"Contacts retained: {totals['contactsRetained']}  eligible: "
                     f"{totals['contactsEligible']}  already archived: {totals['contactsAlreadyArchived']}")
        lines.append(f"Messages retained: {totals['messagesRetained']}  eligible: "
                     f"{totals['messagesEligible']}")
        lines.append(f"Selected contacts kept: {totals['keptSelectedContacts']} with "
                     f"{totals['keptSelectedMessages']} messages")
    lines.append("")
    lines.append("Per contact (hashed label, masked phone, counts only):")
    for c in report.get("contacts", []):
        mc = c["messageCounts"]
        per_table = " ".join(f"{t}={mc[t]['total']}" for t in MESSAGE_TABLES)
        lines.append(f"  {c['label']} {c['maskedPhone'] or '-'} {c['classification']} "
                     f"msgs[{per_table}] financial={c['financialMessages']} "
                     f"uncertain={c['uncertainMessages']}")
    lines.append("")
    eligible = report.get("eligible", [])
    lines.append(f"Eligible for the approved Archive action ({len(eligible)}); exact ids are only "
                 "in the --output report:")
    for e in eligible:
        lines.append(f"  {mask_contact_id(e['contactId'])} {e['maskedPhone'] or '-'} "
                     f"messages={e['messageTotal']}")
    ttl = report.get("ttl") or {}
    if ttl:
        lines.append("")
        lines.append("TTL gap check:")
        for t, s in ttl["ttlState"].items():
            lines.append(f"  {t}: {s}")
        for t, row in ttl["perTable"].items():
            lines.append(f"  {t}: protected={row['protectedMessages']} withExpiry={row['withExpiry']} "
                         f"expiringWithin{ttl['warnDays']}d={row['expiringSoon']} "
                         f"alreadyPast={row['alreadyExpired']}")
        lines.append(f"  at-risk messages listed in the JSON report: {len(ttl['atRisk'])}")
        lines.append("  " + ttl["remediation"])
    lines.append("")
    lines.append(report.get("followUp", ""))
    return "\n".join(lines)


def _git(args: List[str], cwd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=20)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 128, ""


def _has_git_ancestor(directory: str) -> bool:
    current = os.path.abspath(directory)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def refuse_if_tracked_location(path: str) -> Optional[str]:
    """Return an error text if `path` is inside a git work tree and is not gitignored."""
    absolute = os.path.abspath(path)
    directory = os.path.dirname(absolute) or "."
    probe = directory
    while probe and not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    code, top = _git(["rev-parse", "--show-toplevel"], probe or ".")
    if code != 0 or not top:
        if _has_git_ancestor(probe or "."):
            return (f"refusing to use {os.path.basename(absolute)}: it is under a directory with a "
                    ".git ancestor and git could not confirm it is gitignored.")
        return None
    code, _ = _git(["check-ignore", "-q", absolute], probe or ".")
    if code == 0:
        return None
    return (f"refusing to use {os.path.basename(absolute)}: it is inside a git work tree and not "
            "gitignored. Use a path outside the repository.")


def write_report(path: str, report: Dict[str, Any]) -> None:
    absolute = os.path.abspath(path)
    tmp = f"{absolute}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        os.replace(tmp, absolute)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only contact cleanup dry run.")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--table-prefix", default=os.environ.get("TABLE_PREFIX", DEFAULT_PREFIX),
                   help="prefix for default table names")
    for logical in TABLE_SUFFIXES:
        p.add_argument(f"--{logical}-table", default=None, help=f"override {logical} table name")
    p.add_argument("--keep-config", help="private JSON file: {contactIds, phones, bsuids}")
    p.add_argument("--keep-contact-id", action="append", default=[])
    p.add_argument("--keep-phone", action="append", default=[], help="exact full E.164 phone")
    p.add_argument("--keep-bsuid", action="append", default=[])
    p.add_argument("--expect-keep-contacts", type=int, default=None)
    p.add_argument("--expect-keep-messages", type=int, default=None)
    p.add_argument("--ttl-warn-days", type=int, default=90)
    p.add_argument("--output", help="write the full JSON report here (mode 0600)")
    return p


def table_names_from(args: argparse.Namespace) -> Dict[str, str]:
    return {logical: (getattr(args, f"{logical}_table") or f"{args.table_prefix}-{suffix}")
            for logical, suffix in TABLE_SUFFIXES.items()}


def _default_backend(region: str) -> Tuple[Callable[[str], Any], Any]:
    import boto3  # imported late so tests and --help work without AWS

    resource = boto3.resource("dynamodb", region_name=region)
    client = boto3.client("dynamodb", region_name=region)
    return resource.Table, client


def main(argv: Optional[List[str]] = None,
         backend: Optional[Callable[[str], Tuple[Callable[[str], Any], Any]]] = None) -> int:
    """`backend(region)` returns (table_factory, ttl_client); tests inject fakes."""
    args = build_parser().parse_args(argv)
    try:
        selection = Selection(args.keep_contact_id, args.keep_phone, args.keep_bsuid)
        if args.keep_config:
            problem = refuse_if_tracked_location(args.keep_config)
            if problem:
                print(problem, file=sys.stderr)
                return 64
            from_file = load_selection_file(args.keep_config)
            selection = Selection(selection.contact_ids + from_file.contact_ids,
                                  selection.phones + from_file.phones,
                                  selection.bsuids + from_file.bsuids)
    except (OSError, ValueError) as exc:
        print(f"selection file error: {type(exc).__name__}", file=sys.stderr)
        return 64
    if selection.empty():
        print("supply at least one of --keep-config, --keep-contact-id, --keep-phone, --keep-bsuid",
              file=sys.stderr)
        return 64
    if args.output:
        problem = refuse_if_tracked_location(args.output)
        if problem:
            print(problem, file=sys.stderr)
            return 64

    names = table_names_from(args)
    factory, ttl_client = (backend or _default_backend)(args.region)
    tables = {logical: factory(name) for logical, name in names.items()}
    report = classify(tables, selection, ttl_warn_days=args.ttl_warn_days, ttl_client=ttl_client,
                      table_names=names, expect_keep_contacts=args.expect_keep_contacts,
                      expect_keep_messages=args.expect_keep_messages)
    print(render_summary(report))
    if args.output:
        write_report(args.output, report)
        print(f"Full report written to {os.path.basename(args.output)} (mode 0600).")
    if report["status"] == "BLOCKED_SELECTION_MISMATCH":
        return 3
    if report["status"] == "INCOMPLETE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
