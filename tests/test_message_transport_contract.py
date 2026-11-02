"""Execute send boundaries without credentials, provider calls or customer data."""
import ast
import json
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def isolated(path, name, **overrides):
    tree = ast.parse(read(path))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {'Dict': Dict, 'Any': Any, 'Optional': Optional, 'json': json, 'logger': SimpleNamespace(warning=lambda *a: None),
           '_resp': lambda code, data: {'statusCode': code, 'body': data}, **overrides}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), env)
    return env[name]


class MessageTransportTests(unittest.TestCase):
    def test_business_wire_rejects_unknown_types_before_provider_call(self):
        calls = []
        sender = isolated('amplify/functions/messaging/whatsapp-business-api/handler.py', '_send_message',
                          _graph_api=lambda *a, **kw: calls.append(kw) or {'messages': [{'id': 'test-id'}]})
        for kind in ('interactive', 'unknown', '', None):
            result = sender('sender', {'type': kind}, {'to': 'test-recipient'})
            self.assertEqual(result['statusCode'], 400)
        self.assertEqual(calls, [])
        result = sender('sender', {'type': 'template', 'template': {'name': 'approved-test'}}, {'to': 'test-recipient'})
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['payload']['type'], 'template')

    def test_unknown_send_route_has_no_session_or_sender_side_effect(self):
        dispatch = isolated('amplify/functions/messaging/whatsapp-business-api/handler.py', '_route_send_message')
        for suffix in ('interactive', 'flow', 'product', 'products', 'request-contact-info', 'unknown'):
            self.assertEqual(dispatch('/messages/send/' + suffix, {})['statusCode'], 404)

    def test_outbound_wire_rejects_unknown_or_malformed_payload_before_credentials(self):
        sender = isolated('amplify/functions/messaging/outbound-whatsapp/handler.py', '_send_direct_api')
        for value in ('not json', '{}', '[]', '{"type":"interactive"}', '{"type":"unknown"}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                sender('sender', value)

    def test_supported_read_and_typing_controls_pass_type_validation(self):
        class TransportBoundaryReached(Exception):
            pass
        def transport_boundary():
            raise TransportBoundaryReached()
        sender = isolated('amplify/functions/messaging/outbound-whatsapp/handler.py', '_send_direct_api',
                          live_smoke=SimpleNamespace(is_smoke_mode=transport_boundary))
        for control in ({'status': 'read', 'message_id': 'test-wamid'},
                        {'status': 'read', 'message_id': 'test-wamid', 'typing_indicator': {'type': 'text'}}):
            with self.subTest(control=control), self.assertRaises(TransportBoundaryReached):
                sender('sender', control)
        with self.assertRaises(ValueError):
            sender('sender', {'status': 'read', 'message_id': 'test-wamid', 'arbitrary': {}})

    def test_request_fields_reject_removed_modes_before_authorization(self):
        path = 'amplify/functions/messaging/outbound-whatsapp/handler.py'
        tree = ast.parse(read(path))
        schema = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == '_SEND_FIELDS' for t in n.targets))
        fields = frozenset(ast.literal_eval(schema.value.args[0]))
        class AuthorizationReached(Exception):
            pass
        def authorize(*a, **kw):
            raise AuthorizationReached()
        handler = isolated(path, 'handler', _SEND_FIELDS=fields, SEND_MODE='LIVE',
                           extract_origin=lambda event: '', require_auth=authorize,
                           logger=SimpleNamespace(info=lambda *a: None),
                           _error_response=lambda code, *a: {'statusCode': code})
        for payload in ({'isInteractive': True}, {'interactive': {}}, {'isInteractivePayment': True},
                        {'isPaymentTemplate': True}, {'orderDetails': {}}, {'arbitraryField': True}):
            self.assertEqual(handler({'body': json.dumps(payload)}, None)['statusCode'], 400)
        with self.assertRaises(AuthorizationReached):
            handler({'body': json.dumps({'isTemplate': True, 'templateName': 'approved-test'})}, None)

    def test_reply_worker_does_not_send_unsupported_payloads(self):
        sender = isolated('amplify/functions/messaging/inbound-whatsapp-handler/handler.py', '_send_direct_api_message')
        self.assertEqual(sender('recipient', {'type': 'interactive'})['detail'], 'UNSUPPORTED_MESSAGE_TYPE')

    def test_all_production_builders_use_supported_top_level_types(self):
        # Check explicit construction of the removed standalone wire envelope anywhere in production.
        for path in (ROOT / 'amplify/functions').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if isinstance(key, ast.Constant) and key.value == 'type' and isinstance(value, ast.Constant):
                            self.assertNotEqual(value.value, 'interactive', str(path))
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value == 'interactive':
                    for target in node.targets:
                        if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                            self.assertNotEqual(target.slice.value, 'type', str(path))

    def test_refactored_sender_call_signatures_match(self):
        targets = {'_send_template_msg', '_route_send_message', '_handle_live_send',
                   '_build_message_payload', '_send_service_link', '_send_call_followup_text'}
        for path in (ROOT / 'amplify/functions/messaging').rglob('handler.py'):
            tree = ast.parse(path.read_text())
            definitions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in targets}
            for name, definition in definitions.items():
                args = definition.args
                parameters = []
                required = len(args.args) - len(args.defaults)
                for index, arg in enumerate(args.args):
                    parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=inspect.Parameter.empty if index < required else None))
                if args.vararg:
                    parameters.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
                for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                    parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY,
                        default=inspect.Parameter.empty if default is None else None))
                if args.kwarg:
                    parameters.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
                signature = inspect.Signature(parameters)
                for call in ast.walk(tree):
                    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name):
                        continue
                    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(k.arg is None for k in call.keywords):
                        continue
                    with self.subTest(path=str(path), function=name, line=call.lineno):
                        signature.bind(*[None for _ in call.args], **{k.arg: None for k in call.keywords})

    def test_legacy_ai_implementation_and_routes_remain_absent(self):
        for path in ('amplify/functions/ai/ai-generate-response/handler.py', 'src/components/FloatingAgent.tsx',
                     'src/components/dashboard/tabs/InternalChatTab.tsx', 'scripts/provision_agent_approval_routes.py'):
            self.assertFalse((ROOT / path).exists())
        routes = json.loads(read('_routes.json'))
        for route in ('POST /ai/generate', 'POST /ai/approvals', 'POST /ai/approvals/status'):
            self.assertNotIn(route, routes)


if __name__ == '__main__':
    unittest.main()


class VaultCapturedEvidenceTests(unittest.TestCase):
    def test_captured_invoice_exposes_bound_logs_without_accepting_unpaid_states(self):
        path = 'amplify/functions/core/secure-files/handler.py'
        item = dict(fileId='file', ownerCustomerId='customer', ownerPhone='owner', vaultEntitlementId='ent')
        entitlement = dict(grantId='ent', recordType='VAULT_ENTITLEMENT', entitlementState='ACTIVE',
                           customerId='customer', ownerPhone='owner', fileId='file', sourceGrantId='grant')
        grant = dict(paid=True, customerId='customer', ownerPhone='owner', fileId='file',
                     entitlementId='ent', reference='reference')
        invoice = dict(referenceId='reference', invoiceId='invoice', paymentStatus='captured')
        class Table:
            def __init__(self, name): self.name = name
            def get_item(self, **kw):
                return {'Item': entitlement if kw['Key'].get('grantId') == 'ent' else grant}
            def query(self, **kw):
                if self.name == 'invoices': return {'Items': [invoice]}
                if self.name == 'logs': return {'Items': [dict(channel='whatsapp', status='sent', waMessageId='wamid.fixture', timestamp=42)]}
                return {'Items': []}
        reader = isolated(path, '_verified_vault_payment_evidence',
                          _table=Table, GRANTS_TABLE='grants', SERVICE_REQUESTS_TABLE='requests',
                          os=SimpleNamespace(environ={'INVOICES_TABLE':'invoices','INVOICE_DELIVERY_TABLE':'logs'}),
                          _logged_send_evidence=lambda wamid, at: {'status':'ACCEPTED','observedAt':at})
        for state in ('captured', 'paid'):
            invoice['paymentStatus'] = state
            self.assertEqual(reader(item)['invoice']['status'], 'ACCEPTED')
        for state in ('pending', 'failed', 'refunded', 'authorized'):
            invoice['paymentStatus'] = state
            self.assertEqual(reader(item)['invoice']['status'], 'NOT_TRACKED')
