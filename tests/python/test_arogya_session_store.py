"""Fenced encrypted provider custody, using SDK-shaped fakes without AWS access."""
import copy
from types import SimpleNamespace
import pytest
from lambda_utils.arogya.session_store import EncryptedSessionStore, RenewalLeaseLost


class ConditionFailed(Exception): pass


class Table:
    def __init__(self):
        self.row = {}
        self.meta = SimpleNamespace(client=SimpleNamespace(exceptions=SimpleNamespace(ConditionalCheckFailedException=ConditionFailed)))
    def get_item(self, **kwargs):
        assert kwargs['ConsistentRead'] is True
        return {'Item': copy.deepcopy(self.row)}
    def update_item(self, **kwargs):
        expression, condition, values = kwargs['UpdateExpression'], kwargs['ConditionExpression'], kwargs['ExpressionAttributeValues']
        if 'attribute_not_exists(renewalUntil)' in condition:
            if self.row.get('renewalUntil', 0) > values[':now']: raise ConditionFailed()
            self.row.update(pk=kwargs['Key']['pk'], renewalLease=values[':lease'], renewalUntil=values[':until'])
        elif expression.startswith('SET cipher'):
            if self.row.get('renewalLease') != values[':lease'] or self.row.get('renewalUntil', 0) <= values[':now']: raise ConditionFailed()
            self.row.update(cipher=values[':cipher'], updatedAt=values[':now'])
        else:
            if self.row.get('renewalLease') != values[':lease']: raise ConditionFailed()
            self.row.pop('renewalLease', None)
            self.row.pop('renewalUntil', None)


class Kms:
    def __init__(self): self.blobs = {}; self.contexts = []
    def encrypt(self, **kwargs):
        cipher = ('synthetic-cipher-' + str(len(self.blobs))).encode()
        self.blobs[cipher] = (kwargs['Plaintext'], kwargs['EncryptionContext'])
        self.contexts.append(kwargs['EncryptionContext'])
        return {'CiphertextBlob': cipher}
    def decrypt(self, **kwargs):
        raw, context = self.blobs[kwargs['CiphertextBlob']]
        assert context == kwargs['EncryptionContext']
        return {'Plaintext': raw}


def fixture(now=100):
    table, kms = Table(), Kms()
    store = EncryptedSessionStore(table, kms,
        key_arn='arn:aws:kms:us-east-1:000000000000:key/synthetic',
        record_key='arogya:provider:apollo', clock=lambda: now)
    return store, table, kms


def test_only_one_lease_can_claim_and_plaintext_session_never_enters_the_table():
    store, table, kms = fixture()
    lease = store.claim(now=100, lease_seconds=25)
    assert lease and store.claim(now=100, lease_seconds=25) is None
    store.save(lease, {'stage': 'ready', 'token': 'synthetic-token', 'expiresAt': 500})
    assert 'token' not in table.row
    assert 'synthetic-token' not in repr(table.row)
    assert store.read_under_lease(lease)['token'] == 'synthetic-token'
    assert kms.contexts == [{'purpose': 'arogya-provider', 'record': 'arogya:provider:apollo'}]


def test_expired_worker_cannot_save_or_release_a_newer_lease():
    store, table, _ = fixture(now=130)
    stale = store.claim(now=100, lease_seconds=25)
    current = store.claim(now=130, lease_seconds=25)
    assert stale != current
    with pytest.raises(RenewalLeaseLost): store.read_under_lease(stale)
    with pytest.raises(RenewalLeaseLost): store.save(stale, {'token': 'stale'})
    store.release(stale)
    assert table.row['renewalLease'] == current


def test_kms_direct_encrypt_payload_limit_is_enforced_before_network_call():
    store, _, kms = fixture()
    lease = store.claim(now=100, lease_seconds=25)
    with pytest.raises(ValueError): store.save(lease, {'value': 'x' * 4096})
    assert kms.blobs == {}


def test_other_members_provider_record_keys_cannot_be_selected():
    with pytest.raises(ValueError):
        EncryptedSessionStore(Table(), Kms(), key_arn='arn:aws:kms:synthetic', record_key='connection:someone:google-cloud')
