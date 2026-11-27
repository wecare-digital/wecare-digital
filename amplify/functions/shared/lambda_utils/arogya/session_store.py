"""Encrypted custody and fenced renewal leases in an existing DynamoDB table.

No new table or KMS key is provisioned. The owning runtime role must be limited
by dynamodb:LeadingKeys and KMS encryption context to these service records.
Do not point this adapter at other members' provider connection rows.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Callable

ALLOWED_KEYS = frozenset({'arogya:provider:apollo', 'arogya:provider:gmail', 'arogya:provider:credentials'})


class RenewalLeaseLost(RuntimeError):
    pass


class EncryptedSessionStore:
    def __init__(self, table, kms_client, *, key_arn: str, record_key: str,
                 clock: Callable = time.time):
        if record_key not in ALLOWED_KEYS or not key_arn.startswith('arn:aws:kms:'):
            raise ValueError('Provider custody configuration refused')
        self._table = table
        self._kms = kms_client
        self._key_arn = key_arn
        self._record_key = record_key
        self._clock = clock

    def _context(self):
        return {'purpose': 'arogya-provider', 'record': self._record_key}

    def _row(self):
        return self._table.get_item(Key={'pk': self._record_key}, ConsistentRead=True).get('Item', {})

    def _decode(self, row):
        if not row.get('cipher'):
            return {}
        raw = self._kms.decrypt(KeyId=self._key_arn, CiphertextBlob=bytes(row['cipher']),
                                EncryptionContext=self._context())['Plaintext']
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RenewalLeaseLost('Provider state invalid')
        return value

    def read(self):
        return self._decode(self._row())

    def claim(self, *, now: int, lease_seconds: int):
        if not 5 <= lease_seconds <= 120:
            raise ValueError('Renewal lease duration refused')
        lease = secrets.token_urlsafe(32)
        try:
            self._table.update_item(Key={'pk': self._record_key},
                UpdateExpression='SET renewalLease = :lease, renewalUntil = :until',
                ConditionExpression='attribute_not_exists(renewalUntil) OR renewalUntil <= :now',
                ExpressionAttributeValues={':lease': lease, ':until': now + lease_seconds, ':now': now})
            return lease
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return None

    def read_under_lease(self, lease):
        row = self._row()
        if row.get('renewalLease') != lease or int(row.get('renewalUntil', 0)) <= int(self._clock()):
            raise RenewalLeaseLost('Provider renewal lease lost')
        return self._decode(row)

    def save(self, lease, record):
        raw = json.dumps(record, separators=(',', ':')).encode('utf-8')
        if len(raw) > 4096:
            raise ValueError('Provider custody record exceeded limit')
        cipher = self._kms.encrypt(KeyId=self._key_arn, Plaintext=raw,
                                   EncryptionContext=self._context())['CiphertextBlob']
        try:
            self._table.update_item(Key={'pk': self._record_key},
                UpdateExpression='SET cipher = :cipher, updatedAt = :now',
                ConditionExpression='renewalLease = :lease AND renewalUntil > :now',
                ExpressionAttributeValues={':lease': lease, ':cipher': cipher, ':now': int(self._clock())})
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise RenewalLeaseLost('Provider renewal lease lost') from None

    def release(self, lease):
        try:
            self._table.update_item(Key={'pk': self._record_key},
                UpdateExpression='REMOVE renewalLease, renewalUntil',
                ConditionExpression='renewalLease = :lease',
                ExpressionAttributeValues={':lease': lease})
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            # A stale caller must not release another invocation's newer lease.
            return
