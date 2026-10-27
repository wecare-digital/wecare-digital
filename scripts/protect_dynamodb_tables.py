#!/usr/bin/env python3
"""Enable and verify project-table deletion protection. Never disables protection.

Dry-run by default. Use --apply to protect existing project tables, --verify for
an exit-code check. This protects table deletion, not row deletion. All AWS reads
and mutations are scoped to the production account, region and table prefix.
"""
from __future__ import annotations

import argparse
import json

import boto3

REGION = 'us-east-1'
ACCOUNT = '775261844268'
PREFIX = 'stack-wecare-digital-'
EXPLICIT_TABLES = {'wecare-workspace-mcp'}


def protect(client, *, apply=False):
    rows = []
    for page in client.get_paginator('list_tables').paginate():
        for name in page['TableNames']:
            if not name.startswith(PREFIX) and name not in EXPLICIT_TABLES:
                continue
            table = client.describe_table(TableName=name)['Table']
            before = table.get('DeletionProtectionEnabled', False)
            if apply and not before:
                client.update_table(TableName=name, DeletionProtectionEnabled=True)
                # Verification must read the actual setting, not the requested value.
                table = client.describe_table(TableName=name)['Table']
            rows.append({'table': name, 'protected': bool(table.get('DeletionProtectionEnabled')),
                         'changed': bool(apply and not before)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    session = boto3.Session(region_name=REGION)
    if session.client('sts').get_caller_identity()['Account'] != ACCOUNT:
        raise RuntimeError('Refusing to operate outside the expected AWS account')
    rows = protect(session.client('dynamodb'), apply=args.apply)
    print(json.dumps({'region': REGION, 'account': ACCOUNT, 'tables': rows}, indent=2))
    if not rows:
        raise RuntimeError('No project tables discovered; verification is incomplete')
    return int((args.verify or args.apply) and any(not r['protected'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
