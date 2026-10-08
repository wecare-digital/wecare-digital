#!/usr/bin/env python3
"""Plan/apply the two customer log retention policies with principal and age guards.

Default is read-only. Apply requires wecare-admin, or the explicit project-owner
root opt-in, and when each log
has existed for less than 30 days, so the first policy cannot discard old events.
Older groups need explicit history review; this tool refuses them. No log bodies,
credentials, customer records, resource creation or Lambda deployment are read.
"""
from __future__ import annotations
import argparse
import json
import time
import boto3

ACCOUNT = '775261844268'
EXPECTED_ARN = f'arn:aws:iam::{ACCOUNT}:user/wecare-admin'
OWNER_ROOT_ARN = f'arn:aws:iam::{ACCOUNT}:root'
REGION = 'us-east-1'
GROUPS = ('/aws/lambda/wecare-customer-profile', '/aws/lambda/wecare-customer-session')
RETENTION_DAYS = 30

def build_plan(logs, now_ms):
    plans = []
    for name in GROUPS:
        matches = []
        for page in logs.get_paginator('describe_log_groups').paginate(logGroupNamePrefix=name):
            matches.extend(g for g in page.get('logGroups', []) if g.get('logGroupName') == name)
        if len(matches) != 1:
            plans.append({'name': name, 'status': 'BLOCKED_MISSING_OR_AMBIGUOUS'})
            continue
        group = matches[0]
        age = now_ms - group.get('creationTime', 0)
        current = group.get('retentionInDays')
        if current == RETENTION_DAYS:
            status = 'ALREADY_CONFIGURED'
        elif current is not None:
            status = 'BLOCKED_EXISTING_POLICY_REVIEW'
        elif age < 0 or age >= RETENTION_DAYS * 86400000:
            status = 'BLOCKED_OLDER_HISTORY_REVIEW'
        else:
            status = 'READY'
        plans.append({'name': name, 'status': status, 'previousRetentionDays': current,
                      'proposedRetentionDays': RETENTION_DAYS, 'ageDays': round(age / 86400000, 2)})
    return plans

def execute(sts, logs, apply=False, now_ms=None, owner_authorized_root=False):
    identity = sts.get_caller_identity()
    allowed = identity.get('Account') == ACCOUNT and (
        identity.get('Arn') == EXPECTED_ARN or
        (owner_authorized_root and identity.get('Arn') == OWNER_ROOT_ARN))
    plan = build_plan(logs, int(time.time() * 1000) if now_ms is None else now_ms)
    result = {'identity': {'account': identity.get('Account'), 'arn': identity.get('Arn')},
              'writeIdentityAllowed': allowed, 'applyRequested': apply,
              'ownerAuthorizedRoot': owner_authorized_root, 'plan': plan, 'applied': []}
    if not apply:
        return result
    if not allowed:
        raise PermissionError('Expected project account and IAM user, or explicit owner-authorized root opt-in, required')
    if any(item['status'].startswith('BLOCKED') for item in plan):
        raise ValueError('Retention plan contains a review blocker; no policy changed')
    for item in plan:
        if item['status'] == 'READY':
            logs.put_retention_policy(logGroupName=item['name'], retentionInDays=RETENTION_DAYS)
            result['applied'].append(item['name'])
    verification = build_plan(logs, int(time.time() * 1000) if now_ms is None else now_ms)
    if any(row['status'] != 'ALREADY_CONFIGURED' for row in verification):
        raise RuntimeError('Retention verification failed; preserve plan and inspect configuration')
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--owner-authorized-root', action='store_true',
                        help='Use the project owner root authorization of 2026-10-09; exact account and resource guards still apply')
    args = parser.parse_args()
    session = boto3.Session(profile_name='wecare-prod', region_name=REGION)
    print(json.dumps(execute(session.client('sts'), session.client('logs'), args.apply, owner_authorized_root=args.owner_authorized_root), indent=2))

if __name__ == '__main__':
    main()
