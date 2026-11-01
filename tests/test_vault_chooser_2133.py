"""Regression tests for issue #2133: bounded Vault lookup and reply audit.

Run: python -m unittest discover -s tests -p 'test_vault_chooser_2133.py'
No AWS access, customer messages, payments, or secrets are required.
"""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PICKER_PATH = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/vault_file_picker.py'
CATALOG_PATH = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py'
spec = importlib.util.spec_from_file_location('vault_file_picker_tested', PICKER_PATH)
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)

PHONE = '919000000001'
OWNER = 'customer-uuid-example'


def file_row(number, *, owner=OWNER, state='UNPAID', active=True, phone=PHONE):
    return {'fileId': 'f%d' % number, 'ownerPhone': phone,
            'ownerCustomerId': owner, 'status': 'active' if active else 'revoked',
            'testState': state}


class FakeFiles:
    def __init__(self, pages, rows):
        self.pages, self.rows = pages, {r['fileId']: r for r in rows}
        self.query_calls, self.base_reads = [], []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.pages[len(self.query_calls) - 1]

    def get_item(self, **kwargs):
        self.base_reads.append(kwargs)
        return {'Item': self.rows.get(kwargs['Key']['fileId'], {})}


class FakeKeys:
    def __init__(self, fail_update=False):
        self.records, self.updates, self.fail_update = {}, [], fail_update

    def put_item(self, **kwargs):
        row = dict(kwargs['Item'])
        if row['orderId'] in self.records:
            raise ValueError('ConditionalCheckFailedException')
        self.records[row['orderId']] = row

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        if self.fail_update:
            raise RuntimeError('audit write failed')
        record = self.records[kwargs['Key']['orderId']]
        fields = kwargs['ExpressionAttributeValues']
        record.update(replySendStatus=fields[':s'], replyMessageId=fields[':m'],
                      replySendDetail=fields[':d'])


def page(ids, *, cursor=None):
    response = {'Items': [{'fileId': i} for i in ids],
                'ScannedCount': len(ids)}
    if cursor is not None:
        response['LastEvaluatedKey'] = {'page': cursor}
    return response


def select(fake, **opts):
    return picker.eligible_owner_files(
        fake, PHONE, OWNER, lambda r: r['testState'], **opts,
    )


class VaultFileChooserTests(unittest.TestCase):
    def test_truly_empty_index_is_proven_empty(self):
        choices, exhausted = select(FakeFiles([page([])], []))
        self.assertEqual(choices, [])
        self.assertTrue(exhausted)

    def test_expired_only_is_ineligible_no_renewal(self):
        r = file_row(1, state='EXPIRED')
        choices, exhausted = select(FakeFiles([page(['f1'])], [r]))
        self.assertEqual(choices, [])
        self.assertTrue(exhausted)

    def test_valid_document_after_first_100_is_found(self):
        revoked = [file_row(i, active=False) for i in range(101)]
        valid = file_row(101)
        rows = revoked + [valid]
        pages = [page(['f%d' % i for i in range(k, k + 25)], cursor=k // 25 + 1)
                 for k in (0, 25, 50, 75)]
        pages.append(page(['f100', 'f101']))
        fake = FakeFiles(pages, rows)
        choices, exhausted = select(fake)
        self.assertEqual([r['fileId'] for r, _ in choices], ['f101'])
        self.assertTrue(exhausted)
        self.assertEqual(len(fake.query_calls), 5)
        self.assertEqual(fake.query_calls[1]['ExclusiveStartKey'], {'page': 1})
        self.assertTrue(all(x['ConsistentRead'] for x in fake.base_reads))

    def test_1mb_truncated_page_with_short_items_is_followed(self):
        r = file_row(2)
        fake = FakeFiles([page(['f1'], cursor=1), page(['f2'])],
                         [file_row(1, active=False), r])
        choices, exhausted = select(fake)
        self.assertEqual(len(choices), 1)
        self.assertTrue(exhausted)
        self.assertEqual(len(fake.query_calls), 2)

    def test_bounded_budget_is_not_mistaken_for_no_file(self):
        rows = [file_row(i, active=False) for i in range(300)]
        pages = [page(['f%d' % i for i in range(k, k+25)], cursor=k // 25+1)
                 for k in range(0, 300, 25)]
        fake = FakeFiles(pages, rows)
        choices, exhausted = select(fake)
        self.assertEqual(choices, [])
        self.assertFalse(exhausted)
        self.assertEqual(len(fake.query_calls), 12)
        self.assertEqual(len(fake.base_reads), 300)

    def test_owner_phone_status_and_state_checked_against_base_row(self):
        rows = [file_row(1, owner='someone-else'), file_row(2, phone='919999999999'),
                file_row(3, active=False), file_row(4, state='PAID_UNVERIFIED'),
                file_row(5)]
        fake = FakeFiles([page(['f1','f2','f3','f4','f5'])], rows)
        choices, exhausted = select(fake)
        self.assertEqual([r['fileId'] for r, _ in choices], ['f5'])
        self.assertTrue(exhausted)

    def test_selects_only_ten_file_choices(self):
        rows = [file_row(i) for i in range(15)]
        fake = FakeFiles([page(['f%d' % i for i in range(15)])], rows)
        choices, exhausted = select(fake)
        self.assertEqual(len(choices), 10)
        self.assertFalse(exhausted)

    def test_stuck_cursor_is_not_evidence_of_empty_index(self):
        fake = FakeFiles([page([], cursor=1), page([], cursor=1)], [])
        choices, exhausted = select(fake)
        self.assertEqual(choices, [])
        self.assertFalse(exhausted)

    def test_missing_identity_never_queries(self):
        fake = FakeFiles([], [])
        choices, exhausted = picker.eligible_owner_files(
            fake, '', OWNER, lambda r: 'UNPAID')
        self.assertEqual(choices, [])
        self.assertFalse(exhausted)
        self.assertFalse(fake.query_calls)

    def test_metadata_only_and_no_payment_on_no_file_path(self):
        source = CATALOG_PATH.read_text(encoding='utf-8')
        block = source[source.index('        if not choices:'):
                       source.index('        row[\'fileChoices\']', source.index('        if not choices:'))]
        self.assertIn('send_once_with_audit', block)
        self.assertNotIn('_prepare_payment(', block)
        self.assertIn('index_exhausted', block)
        self.assertIn("base + ('_REPLY_NOT_SENT'", block)


class VaultReplyAcceptanceTests(unittest.TestCase):
    def test_2xx_with_provider_id_is_accepted_not_delivered(self):
        state, wamid, detail = picker.classify_reply_send({
            'statusCode': 200,
            'body': json.dumps({'whatsappMessageId': 'wamid.abc123'}),
        })
        self.assertEqual((state, wamid), ('ACCEPTED', 'wamid.abc123'))
        self.assertIn('handset_unverified', detail)

    def test_2xx_without_id_stays_unknown(self):
        self.assertEqual(picker.classify_reply_send(
            {'statusCode': 200, 'body': '{"status":"ok"}'})[0], 'UNKNOWN')

    def test_refusal_is_rejected(self):
        self.assertEqual(picker.classify_reply_send(
            {'statusCode': 400, 'body': '{"error":"bad"}'})[0], 'REJECTED')

    def test_dry_run_is_not_accepted(self):
        self.assertEqual(picker.classify_reply_send(
            {'statusCode': 200, 'body': '{"status":"dry_run","whatsappMessageId":"fake"}'})[0], 'REJECTED')

    def test_timeout_and_server_error_are_unknown(self):
        self.assertEqual(picker.classify_reply_send(None)[0], 'UNKNOWN')
        self.assertEqual(picker.classify_reply_send({'statusCode': 503})[0], 'UNKNOWN')

    def test_one_shot_reply_records_id_and_protects_duplicate(self):
        keys = FakeKeys()
        row = {'orderId': 'CATALOGSERVICE#one', 'token': 'unique-session-token'}
        sent = []
        def send(idem):
            sent.append(idem)
            return {'statusCode': 200, 'body': '{"whatsappMessageId":"wamid.real"}'}
        result = picker.send_once_with_audit(keys, row, send, row_status='AWAITING_FILE')
        self.assertEqual(result['replyStatus'], 'ACCEPTED')
        self.assertEqual(result['whatsappMessageId'], 'wamid.real')
        self.assertEqual(keys.records[row['orderId']]['replySendStatus'], 'ACCEPTED')
        self.assertEqual(len(sent), 1)
        with self.assertRaises(ValueError):
            picker.send_once_with_audit(keys, row, send, row_status='AWAITING_FILE')
        self.assertEqual(len(sent), 1)

    def test_unknown_send_is_persisted_and_not_retried(self):
        keys = FakeKeys()
        count = [0]
        def timeout(_):
            count[0] += 1
            raise TimeoutError('sender timeout')
        row = {'orderId': 'CATALOGSERVICE#two', 'token': 't2'}
        result = picker.send_once_with_audit(keys, row, timeout,
                                             row_status='FILE_LOOKUP_INCOMPLETE')
        self.assertEqual(result['replyStatus'], 'UNKNOWN')
        self.assertTrue(result['reconciliationRequired'])
        self.assertEqual(keys.records[row['orderId']]['replySendStatus'], 'UNKNOWN')
        self.assertEqual(count[0], 1)

    def test_failed_audit_write_keeps_reconciliation_state(self):
        keys = FakeKeys(fail_update=True)
        row = {'orderId': 'CATALOGSERVICE#three', 'token': 't3'}
        result = picker.send_once_with_audit(
            keys, row,
            lambda _: {'statusCode': 202, 'body': {'whatsappMessageId': 'wamid.xyz'}},
            row_status='AWAITING_FILE')
        self.assertTrue(result['reconciliationRequired'])
        self.assertEqual(result['replyStatus'], 'UNKNOWN')
        self.assertEqual(keys.records[row['orderId']]['replySendStatus'], 'SENDING')


if __name__ == '__main__':
    unittest.main()
