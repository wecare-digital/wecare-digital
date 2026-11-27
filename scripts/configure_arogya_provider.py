#!/usr/bin/env python3
"""Validate and configure the existing Apollo service secret interactively.

No credential is accepted as an argument or printed. --check is read-only and
reports readiness without revealing secret fields. Provisioning never logs in
to Apollo, reads mail, enables automation, or modifies a customer record.
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import re
import sys
import uuid

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'amplify/functions/shared'))
from lambda_utils.arogya.provider_runtime import CatalogueUnavailable, validate_provider_config

REGION = 'us-east-1'
ACCOUNT = '775261844268'
TABLE = 'wecare-workspace-mcp'
MAILBOX = 'wecare.digital.bw@gmail.com'
WEBSITE = 'https://aauser-ic.apollohospitals.com/'
SECRET = 'wecare/arogya/apollo'


def read_configuration(session, owner, key_arn):
    if session.client('sts').get_caller_identity()['Account'] != ACCOUNT:
        raise ValueError('Wrong AWS account')
    workspace = session.client('lambda').get_function_configuration(FunctionName='wecare-workspace-mcp')
    env = workspace.get('Environment', {}).get('Variables', {})
    if env.get('REGISTRY_TABLE') != TABLE:
        raise ValueError('Workspace registry mismatch')
    key = session.client('kms').describe_key(KeyId=env.get('TOKEN_KEY', ''))['KeyMetadata']
    if key.get('Arn') != key_arn or key.get('KeyState') != 'Enabled' or key.get('KeyUsage') != 'ENCRYPT_DECRYPT':
        raise ValueError('Workspace custody key mismatch or unavailable')
    table = session.resource('dynamodb').Table(TABLE)
    grant = table.get_item(Key={'pk': 'connection:' + owner + ':google-gmail-apollo'},
                           ConsistentRead=True).get('Item', {})
    if (grant.get('owner') != owner or grant.get('provider') != 'google-gmail-apollo'
            or grant.get('status') != 'verified' or grant.get('hasRefreshToken') is not True
            or not grant.get('lastVerifiedAt') or not grant.get('cipher')):
        raise ValueError('Selected staff grant has not been verified for offline Gmail access')
    secrets = session.client('secretsmanager')
    descriptor = secrets.describe_secret(SecretId=SECRET)
    arn = descriptor['ARN']
    if not re.fullmatch(r'arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/arogya/apollo-[A-Za-z0-9]+', arn):
        raise ValueError('Unexpected service secret ARN')
    if descriptor.get('DeletedDate'):
        raise ValueError('Service secret is scheduled for deletion')
    current = secrets.get_secret_value(SecretId=arn, VersionStage='AWSCURRENT')
    config = json.loads(current['SecretString'])
    if not isinstance(config, dict) or config.get('username') != MAILBOX or config.get('websiteAddress') != WEBSITE:
        raise ValueError('Secret does not describe the intended Apollo service account')
    return secrets, arn, current['VersionId'], config


def promote(secrets, arn, previous, config):
    # Use a unique temporary label and a compare-and-swap AWSCURRENT move.
    # A concurrent administrator's credential rotation must not be overwritten.
    candidate = str(uuid.uuid4())
    label = 'AROGYA-CANDIDATE-' + candidate
    secrets.put_secret_value(SecretId=arn, ClientRequestToken=candidate,
                             VersionStages=[label], SecretString=json.dumps(config, separators=(',', ':')))
    try:
        secrets.update_secret_version_stage(SecretId=arn, VersionStage='AWSCURRENT',
                                           MoveToVersionId=candidate, RemoveFromVersionId=previous)
    finally:
        try:
            secrets.update_secret_version_stage(SecretId=arn, VersionStage=label,
                                               RemoveFromVersionId=candidate)
        except ClientError:
            print('Temporary candidate label cleanup needs administrator attention.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grant-owner', required=True, help='Exact verified staff OAuth owner hash')
    parser.add_argument('--key-arn', required=True, help='Existing workspace custody KMS key ARN')
    parser.add_argument('--check', action='store_true', help='Report configuration readiness; do not change AWS')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{64}', args.grant_owner):
        parser.error('Invalid grant owner hash')
    if not re.fullmatch(r'arn:aws:kms:us-east-1:775261844268:key/[a-f0-9-]{36}', args.key_arn):
        parser.error('Use the existing approved key in the WECARE AWS account')
    if not args.check and (not sys.stdin.isatty() or not sys.stderr.isatty()):
        parser.error('Run interactively in a secure administrator terminal')
    try:
        session = boto3.Session(region_name=REGION)
        secrets, arn, version, config = read_configuration(session, args.grant_owner, args.key_arn)
        if args.check:
            try:
                validate_provider_config(config, args.grant_owner)
            except CatalogueUnavailable:
                print('Gmail verified; service secret exists but approved configuration is incomplete.')
                return 2
            print('Verified grant and approved service secret configuration present. No provider request made.')
            return 0
        print('This binds the verified staff Gmail grant to Apollo read-only service automation.')
        print('Use only an Apollo-approved interface, exact sender and provider-issued application header.')
        if input('Type APPROVED only if Apollo and the mailbox administrator approved this service use: ') != 'APPROVED':
            parser.error('Service authorization not confirmed')
        if input('Type ROTATED only after rotating the previously exposed password: ') != 'ROTATED':
            parser.error('Rotate the exposed password before activating this service')
        sender = input('Exact approved Apollo OTP sender address: ').strip().lower()
        header = getpass.getpass('Provider-issued service application header: ')
        password = getpass.getpass('Rotated Apollo password (blank only if AWSCURRENT already contains it): ')
        updated = {**config, 'approvedSender': sender, 'applicationHeader': header,
                   'password': password or config.get('password'),
                   'grantOwner': args.grant_owner, 'providerAutomationApproved': True}
        validate_provider_config(updated, args.grant_owner)
        promote(secrets, arn, version, updated)
        # Read the current version back without revealing any values.
        _, _, _, confirmed = read_configuration(session, args.grant_owner, args.key_arn)
        validate_provider_config(confirmed, args.grant_owner)
        if confirmed != updated:
            raise ValueError('A concurrent configuration change occurred')
        print('Approved service secret configured. Public access remains disabled.')
        return 0
    except (ClientError, CatalogueUnavailable, ValueError, KeyError, TypeError):
        print('Apollo provisioning could not be verified. Check grant, key, secret permissions, and approved configuration.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
