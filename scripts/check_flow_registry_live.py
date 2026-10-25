#!/usr/bin/env python3
"""Read-only live check: every contract Flow's FlowRegistry row matches its canonical identity.

Purpose
-------
`lambda_utils.canonical_flows.CANONICAL_CONTRACTS` is the identity of each contract Flow (F001
Subscribe, F002 Leave Review): flowNumber, flowCode, flowType, submissionPrefix and its entry
policy. The FlowRegistryTable row is what the keyword door, the staff send and Flow Hub actually
read. On 2026-10-25 the F002 row still carried the legacy flowCode `WD_IDEA` while the code had
moved to `WD-F002-LEAVE-REVIEW`; this script is the repeatable query that finds that kind of
drift instead of a one-off console read.

Authority and safety
--------------------
READ-ONLY. It performs one consistent GetItem per contract Flow and writes nothing. It prints
only identity and policy fields, never `updatedBy` (a staff identity) or any customer data.
Legacy codes (`legacyFlowCodes`) remain READ aliases for historical FlowSubmission rows; they
must never be a registry row's own flowCode.

Severity
--------
FAIL  a contradiction the runtime enforces (`flow_launch.registry_errors`: flowCode,
      submissionPrefix, entry policy, WABA, publication), a missing row, or a legacy flowCode.
      Any FAIL makes the keyword door and staff sends refuse with `registry_contradiction`.
WARN  descriptive identity the runtime does not enforce (flowNumber, flowType).

Usage:  uv run --no-project --python 3.12 --with boto3==1.43.116 \\
            python scripts/check_flow_registry_live.py [--table NAME] [--region us-east-1]
Exit:   0 no FAIL, 1 at least one FAIL, 2 the check could not run (credentials, access, toolchain).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'amplify' / 'functions' / 'shared'))

from lambda_utils import canonical_flows, flow_launch  # noqa: E402

DEFAULT_TABLE = 'stack-wecare-digital-FlowRegistryTable'
#: Only these attributes are read, so nothing else on the row (e.g. `updatedBy`) can be printed.
FIELDS = ('flowId', 'flowNumber', 'flowCode', 'flowType', 'submissionPrefix', 'entryMode',
          'entryTemplateName', 'requiresPayment', 'wabaId', 'status', 'metaStatus')
DESCRIPTIVE = ('flowNumber', 'flowType')


def _plain(value: Any) -> Any:
    """DynamoDB Decimals and sets as plain values for printing and comparison."""
    if hasattr(value, 'is_integer') and not isinstance(value, bool):
        return int(value) if value == int(value) else float(value)
    return value


def check_row(capability: str, contract: Dict[str, Any],
              row: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(fails, warns) for one contract Flow's registry row. Pure: no AWS access."""
    label = f"{contract['flowNumber']} {contract['label']}"
    fails: List[str] = []
    warns: List[str] = []
    if not row:
        return [f'{label}: no FlowRegistry row for Flow {canonical_flows.canonical_flow_id(capability)}'], []
    code = str(row.get('flowCode') or '')
    if code in contract.get('legacyFlowCodes', ()):
        fails.append(f'{label}: registry flowCode is the legacy read alias {code!r}; '
                     f"the canonical code is {contract['flowCode']!r}")
    fails.extend(f'{label}: {error}' for error in flow_launch.registry_errors(row))
    for field in DESCRIPTIVE:
        stored = str(row.get(field) or '')
        if stored != contract[field]:
            warns.append(f'{label}: {field} is {stored or "<absent>"!r}, contract says '
                         f'{contract[field]!r} (descriptive; not enforced at launch)')
    return fails, warns


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--table', default=DEFAULT_TABLE)
    parser.add_argument('--region', default='us-east-1')
    args = parser.parse_args()
    try:
        import boto3
        table = boto3.resource('dynamodb', region_name=args.region).Table(args.table)
    except Exception as error:  # noqa: BLE001 - toolchain or credential problem
        print(f'FLOW REGISTRY LIVE CHECK COULD NOT RUN: {type(error).__name__}')
        return 2

    all_fails: List[str] = []
    all_warns: List[str] = []
    for capability, contract in canonical_flows.CANONICAL_CONTRACTS.items():
        flow_id = canonical_flows.canonical_flow_id(capability)
        try:
            row = table.get_item(
                Key={'flowId': flow_id}, ConsistentRead=True,
                ProjectionExpression=', '.join(f'#f{i}' for i in range(len(FIELDS))),
                ExpressionAttributeNames={f'#f{i}': name for i, name in enumerate(FIELDS)},
            ).get('Item') or {}
        except Exception as error:  # noqa: BLE001 - access denied, throttling, no table
            print(f'FLOW REGISTRY LIVE CHECK COULD NOT RUN: {capability}: {type(error).__name__}')
            return 2
        shown = {name: _plain(row[name]) for name in FIELDS if name in row}
        print(f"{contract['flowNumber']} {capability:<13} {shown}")
        fails, warns = check_row(capability, contract, row)
        all_fails.extend(fails)
        all_warns.extend(warns)

    for line in all_warns:
        print(f'WARN  {line}')
    for line in all_fails:
        print(f'FAIL  {line}')
    verdict = 'FAILED' if all_fails else 'PASSED'
    print(f'FLOW REGISTRY LIVE CHECK {verdict}: {len(canonical_flows.CANONICAL_CONTRACTS)} contract '
          f'Flow(s), {len(all_fails)} fail, {len(all_warns)} warn (read-only).')
    return 1 if all_fails else 0


if __name__ == '__main__':
    sys.exit(main())
