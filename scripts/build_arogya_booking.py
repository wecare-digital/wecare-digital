#!/usr/bin/env python3
"""Build and independently verify a provider-disabled Arogya release artifact.

No AWS requests, deployment, credential reads or provider calls are performed.
The manifest pins the code and CloudFormation template to the checked-out revision.
Provider activation requires a separate authorized, reviewed infrastructure release.
"""
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'amplify/infra/arogya-booking.json'
STACK = 'wecare-arogya-booking'
ACCOUNT = '775261844268'
REGION = 'us-east-1'
BUCKET = 'cdk-hnb659fds-assets-775261844268-us-east-1'
REQUIRED_MODULES = {
    'handler.py',
    'lambda_utils/customer_auth.py',
    'lambda_utils/arogya/booking_store.py',
    'lambda_utils/arogya/provider_runtime.py',
    'lambda_utils/arogya/session_store.py',
    'lambda_utils/ecommerce/unified_pricing.py',
}


def source_commit():
    # Amplify may provide a source snapshot without a .git directory. Trust only
    # the production build's commit identifier, after its exact-commit CI gate.
    if (ROOT / '.git').exists():
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if os.environ.get('AWS_BRANCH') == 'wecare.digital' and os.environ.get('AWS_COMMIT_ID') != commit:
            raise ValueError('Amplify source commit does not match checkout')
    elif os.environ.get('AWS_BRANCH') == 'wecare.digital' and os.environ.get('AWS_APP_ID') == 'd22dm4b0jn71jw':
        commit = os.environ.get('AWS_COMMIT_ID', '')
    else:
        raise ValueError('A git checkout or the production Amplify source snapshot is required')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid source revision')
    return commit


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _check_disabled_template(template):
    parameters = template['Parameters']
    if parameters['ApolloAutomationEnabled'].get('Default') != 'false':
        raise ValueError('Apollo automation must be disabled by default')
    for name in ('ApolloRegistryTableName', 'ApolloTokenKeyArn',
                 'ApolloGmailGrantOwner', 'ApolloGoogleOAuthSecretArn', 'ApolloServiceSecretArn'):
        if parameters[name].get('Default') != '':
            raise ValueError('Provider configuration must be empty by default')
    function = template['Resources']['Function']['Properties']
    env = function['Environment']['Variables']
    if env['APOLLO_AUTOMATION_ENABLED'] != {
            'Fn::If': ['ApolloReadEnabled', {'Ref': 'ApolloAutomationEnabled'}, 'false']}:
        raise ValueError('Provider activation must be explicitly gated')
    if function['Timeout'] != {'Fn::If': ['ApolloReadEnabled', 60, 15]}:
        raise ValueError('Unexpected provider-disabled Lambda timeout')
    for statement in template['Resources']['Role']['Properties']['Policies'][0]['PolicyDocument']['Statement']:
        if 'Fn::If' in statement:
            condition, _, disabled = statement['Fn::If']
            if condition != 'ApolloReadEnabled' or disabled != {'Ref': 'AWS::NoValue'}:
                raise ValueError('Provider permission is not disabled by default')
        else:
            actions = statement['Action']
            if isinstance(actions, str):
                actions = [actions]
            allowed = {'dynamodb:GetItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem',
                       'dynamodb:Query', 'logs:CreateLogStream', 'logs:PutLogEvents'}
            if set(actions) - allowed:
                raise ValueError('Unexpected unconditional runtime permission')
            resources = statement['Resource']
            if resources not in ({'Fn::GetAtt': ['Bookings', 'Arn']},
                                 {'Fn::Sub': 'arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/wecare-arogya-booking:*'}):
                raise ValueError('Unexpected unconditional runtime resource')
    if set(template['Resources']) != {'Bookings', 'Logs', 'Role', 'Function', 'Url',
                                      'UrlPermission', 'InvokePermission'}:
        raise ValueError('Unexpected infrastructure resource in release')


def verify(output, *, expected_commit=None):
    manifest = json.loads((output / 'manifest.json').read_text())
    archive = output / 'arogya-booking.zip'
    template = output / 'arogya-booking.json'
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).digest()
    expected_key = f'arogya-booking/releases/{digest.hex()}.zip'
    if (manifest.get('stack'), manifest.get('account'), manifest.get('region'), manifest.get('s3Bucket')) != (
            STACK, ACCOUNT, REGION, BUCKET):
        raise ValueError('Release destination does not match Arogya stack')
    if (manifest.get('sha256') != digest.hex()
            or manifest.get('codeSha256') != base64.b64encode(digest).decode()
            or manifest.get('bytes') != len(raw)
            or manifest.get('s3Key') != expected_key
            or manifest.get('templateSha256') != _sha(template.read_bytes())):
        raise ValueError('Release artifact checksum mismatch')
    if expected_commit is not None and manifest.get('sourceCommit') != expected_commit:
        raise ValueError('Release artifact was built from a different source revision')
    if manifest.get('parameters') != {'CodeBucket': BUCKET, 'CodeKey': expected_key,
            'ApolloAutomationEnabled': 'false', 'ApolloRegistryTableName': '',
            'ApolloTokenKeyArn': '', 'ApolloGmailGrantOwner': '', 'ApolloGoogleOAuthSecretArn': '',
            'ApolloServiceSecretArn': ''}:
        raise ValueError('Release parameters must not activate the provider')
    _check_disabled_template(json.loads(template.read_bytes()))
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if not REQUIRED_MODULES.issubset(names) or len(names) != len(set(names)):
            raise ValueError('Missing or duplicated Lambda module')
        for name in names:
            if not name.endswith('.py') or name.startswith('/') or '..' in Path(name).parts:
                raise ValueError('Unexpected Lambda archive entry')
            compile(bundle.read(name), name, 'exec')
    return manifest


def build(output):
    commit = source_commit()
    source_paths = ['amplify/functions/ecommerce/arogya-booking',
                    'amplify/functions/shared/lambda_utils',
                    'amplify/infra/arogya-booking.json', 'scripts/build_arogya_booking.py']
    if (ROOT / '.git').exists():
        changed = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all',
            '--', *source_paths], cwd=ROOT, text=True)
        if changed.strip():
            raise ValueError('Commit source changes before building the release artifact')
    output.mkdir(parents=True, exist_ok=True)
    sources = {'handler.py': ROOT / 'amplify/functions/ecommerce/arogya-booking/handler.py'}
    shared = ROOT / 'amplify/functions/shared'
    for path in (shared / 'lambda_utils').rglob('*.py'):
        if '__pycache__' not in path.parts:
            sources[path.relative_to(shared).as_posix()] = path
    archive = output / 'arogya-booking.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, path in sorted(sources.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).digest()
    key = f'arogya-booking/releases/{digest.hex()}.zip'
    template = TEMPLATE.read_bytes()
    (output / 'arogya-booking.json').write_bytes(template)
    manifest = {'stack': STACK, 'account': ACCOUNT, 'region': REGION,
        's3Bucket': BUCKET, 's3Key': key, 'codeSha256': base64.b64encode(digest).decode(),
        'sha256': digest.hex(), 'bytes': archive.stat().st_size,
        'templateSha256': _sha(template), 'sourceCommit': commit,
        'parameters': {'CodeBucket': BUCKET, 'CodeKey': key,
            'ApolloAutomationEnabled': 'false', 'ApolloRegistryTableName': '',
            'ApolloTokenKeyArn': '', 'ApolloGmailGrantOwner': '', 'ApolloGoogleOAuthSecretArn': '',
            'ApolloServiceSecretArn': ''}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify(output, expected_commit=manifest['sourceCommit'])
    print(json.dumps(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify', action='store_true', help='Verify the staged artifact without rebuilding')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.output, expected_commit=source_commit())))
    else:
        build(args.output)
