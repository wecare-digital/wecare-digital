#!/usr/bin/env python3
"""Generate a joined frontend/backend WECARE.DIGITAL release record.

Read-only. Environment values that can contain credentials or client config are
never emitted. The active account is read from STS and cross-checked against
the resolved CloudFormation stack rather than embedded in source.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import boto3

REGION = 'us-east-1'
AMPLIFY_APP_ID = 'd22dm4b0jn71jw'
AMPLIFY_BRANCH = 'wecare.digital'
FUNCTION = 'wecare-customer-commerce-mcp'
ALIAS = 'live'
STACK = 'wecare-customer-commerce-mcp'
API_NAME = 'wecare-customer-commerce-mcp'


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def canonical_hash(values: list[str]) -> str:
    return hashlib.sha256(
        ('\n'.join(sorted(values)) + '\n').encode()
    ).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', default='')
    parser.add_argument('--region', default=REGION)
    args = parser.parse_args()

    if args.region != REGION:
        raise SystemExit(
            f'Wrong AWS region: {args.region}; expected {REGION}'
        )

    sts = boto3.client('sts', region_name=args.region)
    identity = sts.get_caller_identity()

    amplify = boto3.client('amplify', region_name=args.region)
    jobs = amplify.list_jobs(
        appId=AMPLIFY_APP_ID,
        branchName=AMPLIFY_BRANCH,
        maxResults=10,
    ).get('jobSummaries', [])
    latest = jobs[0] if jobs else {}

    lam = boto3.client('lambda', region_name=args.region)
    alias = lam.get_alias(FunctionName=FUNCTION, Name=ALIAS)
    version = lam.get_function(
        FunctionName=FUNCTION,
        Qualifier=alias['FunctionVersion'],
    )['Configuration']
    safe_env = (version.get('Environment') or {}).get('Variables') or {}

    cfn = boto3.client('cloudformation', region_name=args.region)
    stack = cfn.describe_stacks(StackName=STACK)['Stacks'][0]
    stack_id = str(stack.get('StackId') or '')
    stack_parts = stack_id.split(':')
    stack_account = stack_parts[4] if len(stack_parts) > 4 else ''
    if not stack_account or stack_account != identity['Account']:
        raise SystemExit(
            'The active AWS identity does not own the resolved release stack'
        )

    api = boto3.client('apigatewayv2', region_name=args.region)
    apis = [
        item
        for item in api.get_apis().get('Items', [])
        if item.get('Name') == API_NAME
    ]
    if len(apis) != 1:
        raise SystemExit(
            f'Expected one {API_NAME} API, found {len(apis)}'
        )
    api_row = apis[0]
    route_keys = sorted(
        route['RouteKey']
        for route in api.get_routes(
            ApiId=api_row['ApiId']
        ).get('Items', [])
    )

    manifest = {
        'schemaVersion': 'wecare-release-manifest-v1',
        'capturedAt': datetime.now(timezone.utc).isoformat(),
        'account': identity['Account'],
        'region': args.region,
        'git': {
            'repository': 'wecare-digital/wecare-digital',
            'branch': AMPLIFY_BRANCH,
            'commit': args.commit or git_commit(),
        },
        'frontend': {
            'amplifyAppId': AMPLIFY_APP_ID,
            'branch': AMPLIFY_BRANCH,
            'autoBuild': amplify.get_branch(
                appId=AMPLIFY_APP_ID,
                branchName=AMPLIFY_BRANCH,
            )['branch'].get('enableAutoBuild', False),
            'latestJob': {
                key: str(latest.get(key, ''))
                for key in [
                    'jobId',
                    'status',
                    'commitId',
                    'commitMessage',
                    'startTime',
                    'endTime',
                ]
            },
        },
        'customerCommerce': {
            'stack': STACK,
            'stackStatus': stack['StackStatus'],
            'function': FUNCTION,
            'alias': ALIAS,
            'version': alias['FunctionVersion'],
            'codeSha256': version.get('CodeSha256', ''),
            'lastModified': version.get('LastModified', ''),
            'deploymentRevision': safe_env.get(
                'DEPLOYMENT_REVISION', ''
            ),
            'sourceSha256': safe_env.get('SOURCE_SHA256', ''),
            'apiId': api_row['ApiId'],
            'apiEndpoint': api_row.get('ApiEndpoint', ''),
            'defaultExecuteApiEndpointEnabled': not api_row.get(
                'DisableExecuteApiEndpoint', False
            ),
            'routeCount': len(route_keys),
            'routeSha256': canonical_hash(route_keys),
            'routes': route_keys,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, default=str) + '\n'
    )
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == '__main__':
    main()
