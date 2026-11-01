"""Issue #2133: retired customer WhatsApp Vault chooser, not the staff payment rail.

Run: python -m unittest discover -s tests -p 'test_vault_retirement_2133.py'
Isolated AST function execution needs no AWS credentials, boto3 or actual sends.
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import time
import types
import typing
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FLOW_DIR = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows'
CATALOG = FLOW_DIR / 'catalog_services.py'
AUDIT = FLOW_DIR / 'vault_retirement.py'
INBOUND = ROOT / 'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'

spec = importlib.util.spec_from_file_location('vault_retirement_tested', AUDIT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    chosen = [node for node in tree.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
              and node.name in names]
    if len(chosen) != len(names):
        raise AssertionError('Required functions missing: ' + repr(names))
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class AlreadyClaimed(Exception):
    response = {'Error': {'Code': 'ConditionalCheckFailedException'}}


class FakeKeys:
    def __init__(self, fail_update=False):
        self.rows = {}
        self.fail_update = fail_update

    def put_item(self, *, Item, ConditionExpression):
        if Item['orderId'] in self.rows:
            raise AlreadyClaimed()
        self.rows[Item['orderId']] = dict(Item)

    def update_item(self, *, Key, ExpressionAttributeValues, **_kwargs):
        if self.fail_update:
            raise RuntimeError('audit update unknown')
        row = self.rows[Key['orderId']]
        row.update(replySendStatus=ExpressionAttributeValues[':s'],
                   replyMessageId=ExpressionAttributeValues[':m'],
                   replySendDetail=ExpressionAttributeValues[':d'])


class FakeContacts:
    def get_item(self, **_kwargs):
        return {'Item': {'id': 'contact-1', 'checkoutCustomerId': 'customer-1'}}


class FakeDatabase:
    def __init__(self, keys):
        self.keys = keys

    def Table(self, name):
        if name == 'stack-wecare-digital-CommerceKeys':
            return self.keys
        if name == 'fake-contacts':
            return FakeContacts()
        raise AssertionError('retired path must not read file or payment tables: ' + name)


def event(action, msg='wamid.signed-1', **extra):
    return {'action': action, 'sourceMessageId': msg, 'contactId': 'contact-1',
            'senderPhone': '919000000001', 'phoneNumberId': 'WABA1', **extra}


class CatalogRetirementTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'WHATSAPP_CATALOG_SERVICES_ENABLED': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.keys = FakeKeys()
        self.db = FakeDatabase(self.keys)
        self.sent = []
        self.identity_calls = []
        self.payments = []
        self.sender_response = {'statusCode': 200,
                                'body': json.dumps({'whatsappMessageId': 'wamid.accepted'})}
        self.offer = None

        def send(_client, _row, **body):
            self.sent.append(body)
            return self.sender_response

        def invoke(_client, _function, payload):
            self.identity_calls.append(payload)
            return {'outcome': 'WHATSAPP_IDENTITY_READY',
                    'customerId': 'customer-1', 'phone': '+919000000001'}

        def prepare_drop(_client, _db, _keys, row, _identity, *, notify):
            self.payments.append(('drop', row, notify))
            return {'outcome': 'DROP_DOCS_PREPARED'}

        def prepare_vault(_client, _db, _keys, row, _identity, _state, *, notify):
            self.payments.append(('vault', row, notify))
            return {'outcome': 'HISTORICAL_VAULT_PREPARED'}

        self.ns = {
            'hashlib': hashlib, 'os': os, 'time': time, 'secrets': secrets,
            'boto3': types.SimpleNamespace(resource=lambda *_args, **_kw: self.db),
            'shared_tables': types.SimpleNamespace(contacts_table_name=lambda: 'fake-contacts'),
            'vault_retirement': audit,
            'VAULT_CHOOSER_RETIRED_MESSAGE':
                'Use the individual Access Vault link sent for your document; contact support.',
            'IDENTITY_NOT_READY': 'Cannot verify this WhatsApp checkout.',
            'service_requests': types.SimpleNamespace(VAULT='VAULT', DROP_DOCS='DROP_DOCS'),
            'catalog': types.SimpleNamespace(
                SESSION_PREFIX='CATALOGSERVICE#',
                service_from_lines=lambda lines: dict(lines[0]) if lines else None),
            'customer_auth': types.SimpleNamespace(
                is_cognito_subject=lambda x: x == 'customer-1',
                CustomerIdentity=lambda **kw: types.SimpleNamespace(
                    customer_id=kw['customer_id'], phone=kw['phone']),
                CustomerNotAuthorized=type('NotAuthorized', (Exception,), {})),
            '_send': send, '_invoke': invoke,
            '_send_native_payment': lambda *_args: {'outcome': 'STAFF_PAYMENT_PRESERVED'},
            '_prepare_drop_docs_payment': prepare_drop,
            '_prepare_payment': prepare_vault,
            '_live_offer': lambda *_args: self.offer,
            '_send_access': lambda *_args: {'outcome': 'EXISTING_ACCESS_PRESERVED'},
        }
        load_functions(CATALOG, {'handle', '_retire_vault_chooser',
                                 '_conditional_failed', '_unlock'}, self.ns)

    def test_old_signed_vault_cart_never_creates_identity_file_choice_or_payment(self):
        result = self.ns['handle'](
            event('start', lines=[{'kind': 'VAULT', 'productId': 'old-sku'}]), None)
        self.assertEqual(result['outcome'], 'VAULT_CHOOSER_RETIRED')
        self.assertEqual(result['replyStatus'], 'ACCEPTED')
        self.assertEqual(result['whatsappMessageId'], 'wamid.accepted')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.payments, [])
        self.assertEqual(self.identity_calls, [])
        self.assertNotIn('fileId', json.dumps(self.sent))
        self.assertFalse(any(k.startswith('NATIVESERVICE') for k in self.keys.rows))

    def test_old_list_tap_and_replay_cannot_restore_selecting_session(self):
        old = event('select', token='old-token', fileIndex=0)
        first = self.ns['handle'](old, None)
        second = self.ns['handle'](old, None)
        self.assertEqual(first['outcome'], 'VAULT_CHOOSER_RETIRED')
        self.assertEqual(second['outcome'], 'VAULT_CHOOSER_RETIRED_REPLAY')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.payments, [])
        self.assertEqual(self.identity_calls, [])

    def test_staff_exact_file_payment_still_uses_existing_handler(self):
        result = self.ns['handle'](
            event('sendPayment', fileId='f1', ownerCustomerId='customer-1'), None)
        self.assertEqual(result['outcome'], 'STAFF_PAYMENT_PRESERVED')
        self.assertEqual(self.sent, [])
        self.assertEqual(self.identity_calls, [])

    def test_drop_docs_still_provisions_signed_native_payment(self):
        result = self.ns['handle'](
            event('start', lines=[{'kind': 'DROP_DOCS', 'productId': 'drop'}]), None)
        self.assertEqual(result['outcome'], 'DROP_DOCS_PREPARED')
        self.assertEqual(len(self.identity_calls), 1)
        self.assertEqual(self.identity_calls[0]['sourceMessageId'], 'wamid.signed-1')
        self.assertEqual(len(self.payments), 1)
        self.assertEqual(self.payments[0][0], 'drop')
        self.assertTrue(self.payments[0][2])
        self.assertTrue(any(k.startswith('CATALOGSERVICEMSG#') for k in self.keys.rows))
        self.assertEqual(self.sent, [])

    def test_historical_signed_offer_payment_remains_owner_bound(self):
        self.offer = {'orderId': 'VAULTOFFER#old', 'fileId': 'f1'}
        self.ns['vault'] = types.SimpleNamespace(
            FILES_TABLE='files',
            bind_file=lambda *_args: {'fileId': 'f1'})
        self.ns['_vault_session'] = lambda *_args: {
            'orderId': 'CATALOGSERVICE#historical', 'token': 'historical',
            'kind': 'VAULT', 'phoneNumberId': 'WABA1',
            'customerId': 'customer-1', 'vaultFileId': 'f1'}
        self.ns['_file_state'] = lambda *_args: 'UNPAID'
        ident = types.SimpleNamespace(customer_id='customer-1', phone='+919000000001')
        self.ns['_unlock'](event('unlock', offerToken='old'), None,
                           self.db, self.keys, {'id': 'contact-1'},
                           ident, self.offer, 1234)
        self.assertEqual(self.payments[0][0], 'vault')

    def test_revoked_historical_offer_returns_generic_audited_refusal(self):
        self.offer = {'orderId': 'VAULTOFFER#old', 'fileId': 'secret-other-owner'}
        self.ns['vault'] = types.SimpleNamespace(
            FILES_TABLE='files',
            bind_file=lambda *_args: (_ for _ in ()).throw(
                self.ns['customer_auth'].CustomerNotAuthorized()))
        self.ns['_vault_session'] = lambda *_args: {
            'orderId': 'CATALOGSERVICE#historical', 'token': 'historical',
            'phoneNumberId': 'WABA1', 'kind': 'VAULT'}
        ident = types.SimpleNamespace(customer_id='customer-1', phone='+919000000001')
        result = self.ns['_unlock'](event('unlock', offerToken='old'), None,
                                    self.db, self.keys, {'id': 'contact-1'},
                                    ident, self.offer, 1234)
        self.assertEqual(result['outcome'], 'VAULT_CHOOSER_RETIRED')
        self.assertNotIn('secret-other-owner', json.dumps(self.sent))
        self.assertEqual(self.payments, [])

    def test_accepted_rejected_and_unknown_are_persisted_without_retries(self):
        cases = [
            ({'statusCode': 200, 'body': '{"whatsappMessageId":"wamid.valid"}'},
             'ACCEPTED', 'wamid.valid', 'VAULT_CHOOSER_RETIRED'),
            ({'statusCode': 400, 'body': '{"error":"not allowed"}'},
             'REJECTED', '', 'VAULT_CHOOSER_RETIRED_REPLY_NOT_SENT'),
            ({'statusCode': 200, 'body': '{"status":"ok"}'},
             'UNKNOWN', '', 'VAULT_CHOOSER_RETIRED_REPLY_UNCONFIRMED'),
            ({'statusCode': 503}, 'UNKNOWN', '',
             'VAULT_CHOOSER_RETIRED_REPLY_UNCONFIRMED'),
            (None, 'UNKNOWN', '', 'VAULT_CHOOSER_RETIRED_REPLY_UNCONFIRMED'),
        ]
        for i, (answer, status, wamid, outcome) in enumerate(cases):
            with self.subTest(case=i):
                self.sender_response = answer
                req = event('retiredVault', msg='wamid.case-' + str(i))
                first = self.ns['handle'](req, None)
                self.assertEqual((first['outcome'], first['replyStatus'],
                                  first['whatsappMessageId']), (outcome, status, wamid))
                record = self.keys.rows['VAULTRETIREDNOTICE#' +
                    hashlib.sha256(req['sourceMessageId'].encode()).hexdigest()]
                self.assertEqual(record['replySendStatus'], status)
                self.assertEqual(record['replyMessageId'], wamid)
                n = len(self.sent)
                self.assertEqual(self.ns['handle'](req, None)['outcome'],
                                 'VAULT_CHOOSER_RETIRED_REPLAY')
                self.assertEqual(len(self.sent), n)

    def test_failed_audit_update_is_unconfirmed_not_resent(self):
        self.keys.fail_update = True
        req = event('retiredVault')
        first = self.ns['handle'](req, None)
        self.assertEqual(first['replyStatus'], 'UNKNOWN')
        self.assertTrue(first['reconciliationRequired'])
        self.assertEqual(self.ns['handle'](req, None)['outcome'],
                         'VAULT_CHOOSER_RETIRED_REPLAY')
        self.assertEqual(len(self.sent), 1)


class InboundRoutingTests(unittest.TestCase):
    def test_old_list_tap_and_menu_vault_do_not_select_file(self):
        calls = []
        ns = {
            'os': os, 'json': json, 'logger': types.SimpleNamespace(info=lambda *_: None),
            '_route_retired_vault_notice': lambda *args: calls.append(('retired', args)),
            '_route_paid_drop_docs': lambda *_: calls.append(('drop', None)) or True,
            '_send_wd_leaf_link': lambda *_: None,
            '_send_wd_main_menu': lambda *_: None, '_send_wd_list': lambda *_: True,
            'WD_LISTS': {}, 'WD_LEAF_LINKS': {},
            'mask_contact_id': lambda x: x,
        }
        load_functions(INBOUND, {'_route_wd_list_reply'}, ns)
        for value in ('vaultpick:old-token:2', 'vaultpick:malformed', 'wd_vault'):
            result = ns['_route_wd_list_reply'](
                value, 'contact-1', '919000000001', 'WABA1', 'req', 'wamid.tap')
            self.assertEqual(result, 'vault_retired')
        self.assertEqual(len(calls), 3)
        self.assertEqual(ns['_route_wd_list_reply'](
            'wd_drop_docs', 'contact-1', '919000000001',
            'WABA1', 'req', 'wamid.drop'), 'drop_docs')
        self.assertEqual(calls[-1][0], 'drop')

    def test_signed_cart_is_intercepted_before_catalog_checkout(self):
        calls = []
        basket = types.SimpleNamespace(lines=[{'productId': 'vault'}],
                                       message_id='wamid.cart', dropped=False,
                                       clamped=False, log_fields=lambda: {})
        checkout = types.ModuleType('lambda_utils.ecommerce.catalog_service_checkout')
        checkout.service_from_lines = lambda _lines: {'kind': 'VAULT'}
        checkout.service_refusal = lambda _lines: 'unsupported'
        modules = {
            'lambda_utils': types.ModuleType('lambda_utils'),
            'lambda_utils.ecommerce': types.ModuleType('lambda_utils.ecommerce'),
            'lambda_utils.ecommerce.catalog_service_checkout': checkout,
        }
        ns = {
            'os': os, 'json': json, 'Dict': typing.Dict,
            '_catalog_orders_enabled': lambda: True,
            '_send_context': {'phone_number_id': 'meta-1'},
            'META_PHONE_ID_MAP': {'meta-1': 'WABA1'},
            'whatsapp_basket': types.SimpleNamespace(
                is_business_sender=lambda *_: False,
                e164=lambda *_: '+919000000001',
                parse_order_message=lambda *_: basket),
            'short_purchase': types.SimpleNamespace(enabled=lambda: False),
            '_route_retired_vault_notice': lambda *args: calls.append(args),
            'lambda_client': types.SimpleNamespace(invoke=lambda **kwargs:
                self.fail('Vault catalog must not invoke checkout start')),
            'logger': types.SimpleNamespace(info=lambda *_: None,
                                             warning=lambda *_: None,
                                             error=lambda *_: None),
            '_phone_suffix': lambda *_: '0001',
        }
        load_functions(INBOUND, {'_handle_cart_order'}, ns)
        with mock.patch.dict(os.environ, {'WHATSAPP_CATALOG_SERVICES_ENABLED': 'true'}):
            with mock.patch.dict(sys.modules, modules):
                ns['_handle_cart_order']({}, 'contact-1', '919000000001',
                                         'WABA1', 'req')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], 'wamid.cart')

    def test_keyword_and_tokenless_offer_never_call_catalog_start(self):
        source = INBOUND.read_text(encoding='utf-8')
        keyword = source[source.index("if _content_plain in {'vault', 'my vault'}:"):
                         source.index("if (_content_plain == 'drop docs'", source.index(
                             "if _content_plain in {'vault', 'my vault'}:"))]
        self.assertIn('_route_retired_vault_notice(', keyword)
        self.assertNotIn("'action': 'start'", keyword)
        offer = source[source.index('def _route_vault_offer_tap('):
                       source.index('def _extract_content(', source.index(
                           'def _route_vault_offer_tap('))]
        self.assertIn("if not token:", offer)
        self.assertNotIn("'action': 'start'", offer)
        self.assertIn("'action': 'unlock'", offer)


if __name__ == '__main__':
    unittest.main()
