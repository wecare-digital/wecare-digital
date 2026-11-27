#!/usr/bin/env python3
"""Explicit administrator provisioning; credentials are entered on the operator's terminal.

No credential values are accepted as arguments, printed, written to disk or returned.
This script creates no infrastructure, never reads mail, never logs in to Apollo,
and never enables the public catalogue. The selected staff grant must already be
verified, and the operator must have provider approval for service-account access.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys

import boto3

REGION = 'us-east-1'
ACCOUNT = '775261844268'
TABLE = 'wecare-workspace-mcp'
MAILBOX = 'wecare.digital.bw@gmail.com'
RECORD = 'arogya:provider:credentials'
CONTEXT = {'purpose': 'arogya-provider', 'record': RECORD}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grant-owner', required=True, help='Exact verified staff OAuth owner hash')
    parser.add_argument('--key-arn', required=True, help='Existing approved provider-custody KMS key ARN')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{64}', args.grant_owner):
        parser.error('Invalid grant owner hash')
    if not re.fullmatch(r'arn:aws:kms:us-east-1:775261844268:key/[a-f0-9-]{36}', args.key_arn):
        parser.error('Use the approved key in the WECARE AWS account')
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error('Run interactively in a secure administrator terminal')
    session = boto3.Session(region_name=REGION)
    if session.client('sts').get_caller_identity()['Account'] != ACCOUNT:
        parser.error('Wrong AWS account')
    table = session.resource('dynamodb').Table(TABLE)
    key = {'pk': 'connection:' + args.grant_owner + ':google-gmail-apollo'}
    grant = table.get_item(Key=key, ConsistentRead=True).get('Item', {})
    if (grant.get('owner') != args.grant_owner or grant.get('provider') != 'google-gmail-apollo'
            or grant.get('status') != 'verified' or grant.get('hasRefreshToken') is not True
            or not grant.get('lastVerifiedAt') or not grant.get('cipher')):
        parser.error('Selected staff grant has not been verified for offline Gmail access')
    if table.get_item(Key={'pk': RECORD}, ConsistentRead=True).get('Item'):
        parser.error('Credential record already exists; use the approved rotation and session reset procedure')
    print('This binds the selected verified Gmail grant to Apollo read-only service automation.')
    print('Use only a provider-issued application header and a rotated service password.')
    if input('Type APPROVED only if Apollo and the mailbox administrator approved this service use: ') != 'APPROVED':
        parser.error('Service authorization not confirmed')
    sender = input('Exact approved Apollo OTP sender address: ').strip().lower()
    if not re.fullmatch(r'[^\s@]+@(?:[a-z0-9-]+\.)*apollohospitals\.com', sender):
        parser.error('Sender must be an exact approved Apollo address')
    password = getpass.getpass('Rotated Apollo service password: ')
    header = getpass.getpass('Provider-issued service application header: ')
    if not password or len(password) > 1024 or not header or len(header) > 2048 or '\n' in header or '\r' in header:
        parser.error('Missing or invalid service credentials')
    config = {'username': MAILBOX, 'password': password, 'applicationHeader': header,
              'approvedSender': sender, 'grantOwner': args.grant_owner, 'providerAutomationApproved': True}
    raw = json.dumps(config, separators=(',', ':')).encode()
    if len(raw) > 4096:
        parser.error('Encrypted credential record exceeded size limit')
    ciphertext = session.client('kms').encrypt(KeyId=args.key_arn, Plaintext=raw,
        EncryptionContext=CONTEXT)['CiphertextBlob']
    table.put_item(Item={'pk': RECORD, 'cipher': ciphertext},
        ConditionExpression='attribute_not_exists(pk)')
    print('Encrypted service credential record created. Public access remains disabled.')


if __name__ == '__main__':
    main()
