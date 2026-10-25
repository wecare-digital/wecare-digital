"""Offline checks for conversation-only commerce. No providers or customer traffic."""
from __future__ import annotations

from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'amplify/functions/ecommerce/customer-commerce-mcp'))
SPEC = importlib.util.spec_from_file_location('commerce_mcp', ROOT / 'amplify/functions/ecommerce/customer-commerce-mcp/handler.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


def event(body=None, token='', path='/mcp', method='POST', origin=''):
    return {'rawPath': path, 'headers': {'origin': origin, 'authorization': token},
            'requestContext': {'http': {'method': method, 'sourceIp': '127.0.0.1'}},
            'body': json.dumps(body if body is not None else {})}


def call(name, args=None, token=''):
    response = app.handler(event({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                  'params': {'name': name, 'arguments': args or {}}}, token), None)
    return json.loads(response['body'])['result']


PRODUCT = {'id': 'approved-kit', 'name': 'Approved kit', 'currency': 'INR', 'description': 'Example product',
           'variants': [{'id': 'standard', 'label': 'Standard', 'amountPaise': 89900}]}
ITEMS = [{'productId': 'approved-kit', 'variantId': 'standard', 'quantity': 2}]


class ConversationContract(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'CUSTOMER_COMMERCE_ORIGIN': 'https://commerce.example.com',
                                     'CHATGPT_APPROVED_PRODUCT_IDS': '[]',
                                     'WHATSAPP_PAYMENT_REQUESTS_ENABLED': 'false', 'CUSTOMER_AUTHORIZATION_SERVER': ''})
        env.start()
        self.addCleanup(env.stop)
        authorization = patch.object(app.customer_oauth, 'customer_event', side_effect=lambda event, scope: event)
        authorization.start()
        self.addCleanup(authorization.stop)

    def test_default_approval_list_is_empty(self):
        self.assertEqual(app.catalog(), [])

    def test_duplicate_approval_ids_refused(self):
        with patch.dict(os.environ, {'CHATGPT_APPROVED_PRODUCT_IDS': '["a","a"]'}):
            self.assertRaises(ValueError, app.approved_ids)

    def test_product_requires_active_inr_and_verified_inventory(self):
        row = {'id': 'a', 'title': 'Kit', 'status': 'active', 'currency': 'INR',
               'variants': [{'sku': 'v', 'priceMinor': 100, 'inventoryVerified': True, 'trackInventory': False}]}
        self.assertEqual(app.project_product(row)['variants'][0]['amountPaise'], 100)
        row['variants'][0]['inventoryVerified'] = False
        self.assertIsNone(app.project_product(row))
        row['variants'][0].update(inventoryVerified=True, priceMinor=True)
        self.assertIsNone(app.project_product(row))

    def test_finite_integer_money_only(self):
        for value in [True, 1.2, Decimal('NaN'), Decimal('Infinity')]:
            self.assertIsNone(app.integer(value))

    def test_no_html_route_or_mcp_ui_resource(self):
        response = app.handler(event(path='/app', method='GET'), None)
        self.assertEqual(response['statusCode'], 404)
        response = app.handler(event({'jsonrpc': '2.0', 'id': 1, 'method': 'resources/read'}), None)
        self.assertIn('error', json.loads(response['body']))
        self.assertNotIn('resourceUri', json.dumps(app.tools()))

    def test_tools_are_conversation_actions_without_storefront(self):
        names = {tool['name'] for tool in app.tools()}
        self.assertEqual(names, {'browse_products', 'review_purchase', 'get_my_account', 'update_my_account',
                                'list_my_orders', 'check_my_payment', 'continue_in_whatsapp'})
        self.assertNotIn('open_store', names)
        self.assertNotIn('otp', json.dumps([t['inputSchema'] for t in app.tools()]).lower())
        self.assertNotIn('token', json.dumps([t['inputSchema'] for t in app.tools()]).lower())

    def test_no_images_in_product_tool_result(self):
        with patch.object(app, 'catalog', return_value=[PRODUCT]):
            result = call('browse_products')
            self.assertEqual(result['structuredContent']['products'], [PRODUCT])
            self.assertNotIn('image', json.dumps(result))

    def test_account_tools_require_host_connection_before_delegation(self):
        with patch.object(app, 'delegate') as delegate:
            result = call('get_my_account')
            self.assertTrue(result['isError'])
            self.assertEqual(result['structuredContent']['status'], 'SIGN_IN_REQUIRED')
            self.assertIn('mcp/www_authenticate', result['_meta'])
            delegate.assert_not_called()

    def test_account_uses_fixed_handler_and_original_token(self):
        with patch.object(app, 'delegate', return_value=app.reply(200, {'status': 'PROFILE_REQUIRED'})) as delegate:
            result = call('get_my_account', token='Bearer test')
            self.assertFalse(result['isError'])
            function, body, original, path = delegate.call_args.args
            self.assertEqual(function, 'wecare-checkout:live')
            self.assertEqual(body, {'action': 'profile'})
            self.assertEqual(original['headers']['authorization'], 'Bearer test')

    def test_browser_cannot_choose_identity(self):
        with patch.object(app, 'delegate') as delegate:
            self.assertTrue(call('list_my_orders', {'customerId': 'another-person'}, 'Bearer test')['isError'])
            delegate.assert_not_called()

    def test_staff_or_expired_token_refusal_is_not_success(self):
        with patch.object(app, 'delegate', return_value=app.reply(401, {'error': 'VERIFICATION_REQUIRED'})):
            result = call('get_my_account', token='Bearer invalid')
            self.assertTrue(result['isError'])
            self.assertIn('mcp/www_authenticate', result['_meta'])

    def test_profile_write_annotation_and_field_validation(self):
        descriptor = next(t for t in app.tools() if t['name'] == 'update_my_account')
        self.assertFalse(descriptor['annotations']['readOnlyHint'])
        with patch.object(app, 'delegate') as delegate:
            result = call('update_my_account', {'address': {'postalCode': '000001'}}, 'Bearer test')
            self.assertTrue(result['isError'])
            delegate.assert_not_called()

    def test_profile_changes_delegate_only_customer_fields(self):
        with patch.object(app, 'delegate', return_value=app.reply(200, {'status': 'PROFILE_READY'})) as delegate:
            result = call('update_my_account', {'firstName': 'Example'}, 'Bearer test')
            self.assertFalse(result['isError'])
            self.assertEqual(delegate.call_args.args[0], 'wecare-customer-profile:live')
            self.assertEqual(delegate.call_args.args[1], {'firstName': 'Example'})

    def test_review_uses_catalog_prices_and_is_only_an_estimate(self):
        with patch.object(app, 'catalog', return_value=[PRODUCT]):
            result = call('review_purchase', {'items': ITEMS})['structuredContent']
            self.assertEqual(result['itemsEstimatePaise'], 179800)
            self.assertFalse(result['finalPayableTotalAvailable'])
            self.assertFalse(result['paymentCollected'])
            self.assertFalse(result['inChatPaymentEnabled'])
            self.assertEqual(result['paymentOptions'], [])

    def test_whatsapp_fallback_is_offered_only_when_enabled(self):
        with patch.dict(os.environ, {'WHATSAPP_PAYMENT_REQUESTS_ENABLED': 'true'}), patch.object(app, 'catalog', return_value=[PRODUCT]):
            result = call('review_purchase', {'items': ITEMS})['structuredContent']
            self.assertEqual(result['paymentOptions'][0]['label'], 'Pay on WhatsApp')
            self.assertTrue(result['paymentOptions'][0]['requiresCustomerConfirmation'])
            self.assertFalse(result['paymentCollected'])

    def test_client_price_and_unapproved_items_refused(self):
        hostile = [{**ITEMS[0], 'unitAmountPaise': 1}]
        self.assertTrue(call('review_purchase', {'items': hostile})['isError'])
        self.assertTrue(call('review_purchase', {'items': ITEMS})['isError'])

    def test_payment_sending_absent_until_explicit_activation(self):
        self.assertNotIn('request_whatsapp_payment', {t['name'] for t in app.tools()})
        self.assertTrue(call('request_whatsapp_payment', {'items': ITEMS, 'idempotencyKey': 'example-request-001'})['isError'])

    def test_enabled_send_preserves_idempotency_and_sends_no_price_or_phone(self):
        with patch.dict(os.environ, {'WHATSAPP_PAYMENT_REQUESTS_ENABLED': 'true'}), patch.object(app, 'catalog', return_value=[PRODUCT]), patch.object(app, 'delegate', return_value=app.reply(200, {'status': 'PAYMENT_REQUEST_SENT'})) as delegate:
            result = call('request_whatsapp_payment', {'items': ITEMS, 'idempotencyKey': 'example-request-001'}, 'Bearer test')
            self.assertFalse(result['isError'])
            self.assertTrue(result['structuredContent']['messageSent'])
            self.assertFalse(result['structuredContent']['paymentCollected'])
            self.assertIn('complete the transaction there', result['structuredContent']['customerMessage'])
            body = delegate.call_args.args[1]
            self.assertEqual(body['requestKey'], 'example-request-001')
            self.assertEqual(body['action'], 'create')
            self.assertEqual(body['lineItems'][0]['quantity'], 2)
            self.assertNotIn('amount', json.dumps(body).lower())
            self.assertNotIn('phone', json.dumps(body).lower())

    def test_prepared_but_unsent_is_not_reported_as_sent(self):
        with patch.dict(os.environ, {'WHATSAPP_PAYMENT_REQUESTS_ENABLED': 'true'}), patch.object(app, 'catalog', return_value=[PRODUCT]), patch.object(app, 'delegate', return_value=app.reply(200, {'status': 'PAYMENT_INITIATION_DISABLED'})):
            result = call('request_whatsapp_payment', {'items': ITEMS, 'idempotencyKey': 'example-request-001'}, 'Bearer test')
            self.assertTrue(result['isError'])
            self.assertFalse(result['structuredContent']['messageSent'])

    def test_whatsapp_handoff_sends_nothing(self):
        result = call('continue_in_whatsapp', {'purpose': 'orders'})['structuredContent']
        self.assertEqual(result['formLocation'], 'WhatsApp')
        self.assertFalse(result['messageSent'])
        self.assertEqual(result['url'], app.WHATSAPP_ENTRIES['orders'])

    def test_unknown_whatsapp_target_rejected(self):
        self.assertTrue(call('continue_in_whatsapp', {'purpose': 'https://untrusted.example'})['isError'])

    def test_provider_failure_redacted(self):
        with patch.object(app, 'catalog', side_effect=RuntimeError('private-provider-detail')):
            result = call('browse_products')
            self.assertTrue(result['isError'])
            self.assertNotIn('private-provider-detail', json.dumps(result))

    def test_no_fake_oauth_endpoint(self):
        response = app.handler(event(path='/.well-known/oauth-protected-resource', method='GET'), None)
        self.assertEqual(response['statusCode'], 200)
        metadata = json.loads(response['body'])
        self.assertEqual(metadata['authorization_servers'], ['https://commerce.example.com'])

    def test_foreign_browser_origin_refused(self):
        self.assertEqual(app.handler(event(origin='https://untrusted.example'), None)['statusCode'], 403)

    def test_malformed_and_oversize_requests_refused(self):
        self.assertEqual(app.handler(event([]), None)['statusCode'], 400)
        large = event()
        large['body'] = 'x' * (app.MAX_BODY + 1)
        self.assertEqual(app.handler(large, None)['statusCode'], 413)


if __name__ == '__main__':
    unittest.main(verbosity=2)
