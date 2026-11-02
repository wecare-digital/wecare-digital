"""Offline financial-preserving Collect guards; no AWS access or message sends."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock

root = Path(__file__).resolve().parents[1]
package = types.ModuleType('collect_test')
package.__path__ = [str(root / 'amplify/functions/shared/lambda_utils/ecommerce')]
sys.modules['collect_test'] = package
from collect_test import collect_contract as contract, collect_receipts as receipts


class Conflict(Exception):
    response = {'Error': {'Code': 'ConditionalCheckFailedException'}}


class Table:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.race = False

    def get_item(self, Key, **kwargs):
        return {'Item': dict(self.rows.get(next(iter(Key.values())), {}))}

    def put_item(self, Item, **kwargs):
        key = Item['orderId']
        if key in self.rows:
            raise Conflict()
        self.rows[key] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kwargs):
        row = self.rows.setdefault(next(iter(Key.values())), {})
        v = ExpressionAttributeValues
        if 'collectResendRequestId=:intent,' in UpdateExpression:
            if self.race:
                raise Conflict()
            row.update(collectResendRequestId=v[':intent'], collectResendState='SENDING')
        elif 'collectResendState=:state' in UpdateExpression:
            row.update(collectResendState=v[':state'], collectResendMessageId=v[':message'])
        else:
            row['state'] = v[':state']
            if ':message' in v:
                row['waMessageId'] = v[':message']


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.invoice = {'invoiceId':'inv-1','entryPoint':'pay_flow','paymentStatus':'captured',
                        'customerPhone':'+919000000001','paidAt':10}
        self.invoices = Table({'inv-1':self.invoice})
        self.keys = Table()
        self.body = {'_action':'collect-resend','invoiceId':'inv-1','resendRequestId':'a'*32,
                     'previousRequestId':'','expectedAssetKey':'saved.png'}
        self.send = Mock(return_value={'statusCode':200,'body':json.dumps({'status':'sent','waMessageId':'wamid.proof'})})
        self.args = dict(actor='staff',invoices=self.invoices,keys=self.keys,
                         latest_asset=lambda _: {'s3Key':'saved.png','generatedAt':11},
                         recipient_valid=lambda _: True,send=self.send,
                         paid=lambda i:i.get('paymentStatus')=='captured',now=20)

    def run_send(self, body=None):
        return receipts.resend(body or self.body,**self.args)

    def test_same_intent_sends_once(self):
        self.assertEqual(self.run_send()[1]['state'],'ACCEPTED')
        self.assertTrue(self.run_send()[1]['deduplicated'])
        self.assertEqual(self.send.call_count,1)

    def test_altered_intent_refused(self):
        self.run_send()
        self.assertEqual(self.run_send({**self.body,'expectedAssetKey':'different.png'})[0],409)
        self.assertEqual(self.send.call_count,1)

    def test_unknown_outcome_holds_invoice_lock(self):
        self.send.side_effect = TimeoutError()
        self.assertEqual(self.run_send()[1]['state'],'UNCONFIRMED')
        self.run_send()
        self.assertEqual(self.run_send({**self.body,'resendRequestId':'b'*32,'previousRequestId':'a'*32})[0],409)
        self.assertEqual(self.send.call_count,1)

    def test_racing_tab_loses_before_send(self):
        self.invoices.race = True
        self.assertEqual(self.run_send()[0],409)
        self.send.assert_not_called()

    def test_unpaid_and_other_services_never_send(self):
        for change in ({'paymentStatus':'pending'},{'fixedPresetId':'fixed-01'},{'entryPoint':'webhook'},{'serviceKind':'VAULT'}):
            self.invoices.rows['inv-1'] = {**self.invoice,**change}
            self.assertEqual(self.run_send()[0],409)
        self.send.assert_not_called()

    def test_customer_and_image_rechecked(self):
        self.args['recipient_valid'] = lambda _:False
        self.assertEqual(self.run_send()[0],409)
        self.args['recipient_valid'] = lambda _:True
        self.args['latest_asset'] = lambda _: {'s3Key':'saved.png','generatedAt':9}
        self.assertEqual(self.run_send()[0],409)
        self.send.assert_not_called()

    def test_authenticated_staff_required(self):
        self.args['actor']=''
        self.assertEqual(self.run_send()[0],403)
        self.send.assert_not_called()

    def test_server_5xx_is_uncertain(self):
        self.send.return_value={'statusCode':502,'body':'{}'}
        self.assertEqual(self.run_send()[1]['state'],'UNCONFIRMED')

    def test_explicit_refusal_allows_new_reviewed_intent(self):
        self.send.return_value={'statusCode':409,'body':'{}'}
        self.assertEqual(self.run_send()[1]['state'],'REFUSED')
        self.send.return_value={'statusCode':200,'body':json.dumps({'status':'sent','waMessageId':'wamid.next'})}
        self.assertEqual(self.run_send({**self.body,'resendRequestId':'b'*32,'previousRequestId':'a'*32})[1]['state'],'ACCEPTED')
        self.assertEqual(self.send.call_count,2)

    def test_unresolved_automatic_receipt_blocks_manual_send(self):
        self.args['original_ready']=lambda _:False
        self.assertEqual(self.run_send()[0],409)
        self.send.assert_not_called()
        self.assertFalse(self.keys.rows)

    def test_later_callback_resolves_unknown_without_resending(self):
        self.send.side_effect=TimeoutError()
        self.assertEqual(self.run_send()[1]['state'],'UNCONFIRMED')
        self.args['reconcile']=lambda iid,intent,key:{'state':'ACCEPTED','waMessageId':'wamid.later'}
        self.assertEqual(self.run_send()[1]['state'],'ACCEPTED')
        self.assertEqual(self.send.call_count,1)
        self.assertEqual(self.invoices.rows['inv-1']['collectResendState'],'ACCEPTED')

    def test_other_browser_can_reconcile_only_the_stored_intent(self):
        self.send.side_effect=TimeoutError()
        self.run_send()
        code,data=receipts.reconcile_existing('inv-1',actor='other-staff',invoices=self.invoices,
            keys=self.keys,reconcile=lambda *args:{'state':'REFUSED','waMessageId':''},now=30)
        self.assertEqual(code,200)
        self.assertEqual(data['state'],'REFUSED')
        self.assertEqual(self.send.call_count,1)

    def test_missing_later_proof_keeps_unknown_locked(self):
        self.send.side_effect=TimeoutError()
        self.run_send()
        self.args['reconcile']=lambda *args:None
        self.assertEqual(self.run_send()[1]['state'],'UNCONFIRMED')
        self.assertEqual(self.send.call_count,1)

    def test_complete_saved_address_snapshot(self):
        c={'checkoutDeliveryAddress':{'addressLine1':'Street','addressLine2':'Unit','locality':'Area','country':'India','countryCode':'IN'}}
        original=contract.address_snapshot(c)
        for field in ('addressLine2','locality','country','countryCode'):
            changed={'checkoutDeliveryAddress':{**c['checkoutDeliveryAddress'],field:'changed'}}
            self.assertNotEqual(original,contract.address_snapshot(changed))
        self.assertEqual(contract.address_snapshot({'city':'A','landmark':''}),{'city':'A'})

    def test_preview_changes_bind_all_reviewed_fields(self):
        body={'contactId':'customer','customerName':'Name','buyerGstin':'GST',
              'addressLine1':'Street','items':[{'name':'Custom','amount':10,'quantity':1,'gstRate':18}]}
        quote={'subtotal':10,'total':11.8}
        fingerprint=contract.preview_fingerprint(body,quote)
        for field in ('contactId','customerName','customerPhone','buyerGstin','addressLine1','city','state','postalCode'):
            self.assertNotEqual(fingerprint,contract.preview_fingerprint({**body,field:'changed'},quote))
        for field in ('name','amount','quantity','gstRate'):
            item={**body['items'][0],field:'Different' if field=='name' else 2}
            self.assertNotEqual(fingerprint,contract.preview_fingerprint({**body,'items':[item]},quote))
        self.assertNotEqual(fingerprint,contract.preview_fingerprint(body,{**quote,'total':12}))
        self.assertEqual(fingerprint,contract.preview_fingerprint({**body,'items':[{'name':'Custom','amount':'10.00','quantity':'1','gstRate':'18.0'}]},quote))


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        import ast
        from types import SimpleNamespace
        self.ns = SimpleNamespace
        source = (root / 'amplify/functions/payments/invoice-engine/handler.py').read_text()
        names = {'_verified_collect_order_link', '_collect_receipt_delivery', '_send_collect_receipt'}
        tree = ast.parse(source)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.table = Mock()
        self.env = {'Dict':dict, 'List':list, 're':__import__('re'), 'os':__import__('os'),
                    'dynamodb':SimpleNamespace(Table=lambda _:self.table),
                    'shared_tables':SimpleNamespace(orders_table_name=lambda:'orders'),
                    'logger':Mock(), 'json':json, 'order_keys':Mock(), 'send_invoice_whatsapp':Mock(),
                    'COMMERCE_KEYS_TABLE':'keys', 'wa_payment_request':SimpleNamespace(PHONE_NUMBER_ID_1='primary'),
                    '_resp':lambda code,data:{'statusCode':code,'body':json.dumps(data)}, 'boto3':SimpleNamespace(dynamodb=SimpleNamespace(conditions=SimpleNamespace(Key=lambda _:SimpleNamespace(eq=lambda _:True))))}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<isolated projection>', 'exec'),self.env)

    def test_automatic_claim_race_blocks_force_at_send_boundary(self):
        keys=self.env['order_keys'];keys.DELIVERY_CONFIRMED='DELIVERED'
        keys.claim_invoice_delivery.return_value=False
        keys.resolve_invoice_delivery.return_value={'deliveryStatus':'CLAIMED'}
        result=self.env['_send_collect_receipt']('inv','phone','image','intent','request')
        self.assertEqual(result['statusCode'],409)
        self.env['send_invoice_whatsapp'].assert_not_called()

    def test_first_manual_delivery_holds_ordinary_claim_on_timeout(self):
        keys=self.env['order_keys'];keys.claim_invoice_delivery.return_value=True
        self.env['send_invoice_whatsapp'].return_value={'statusCode':202,'body':'{"status":"unknown"}'}
        self.env['_send_collect_receipt']('inv','phone','image','intent','request')
        keys.release_invoice_delivery.assert_not_called()
        keys.confirm_invoice_delivery.assert_not_called()

    def test_rejected_receipt_without_wamid_remains_known_failure(self):
        inv={'invoiceId':'inv','customerPhone':'phone'}
        log={'invoiceId':'inv','channel':'whatsapp','toNumber':'phone','imageS3Key':'image','status':'rejected','waMessageId':''}
        self.assertEqual(self.env['_collect_receipt_delivery'](inv,[log])['status'],'Failed')
        self.table.query.assert_not_called()

    def test_order_link_requires_reciprocal_invoice(self):
        invoice={'invoiceId':'inv','invoiceNumber':'N','internalOrderId':'internal','orderNumber':'public'}
        self.table.get_item.return_value={'Item':{'invoiceId':'different','invoiceNumber':'N','orderNumber':'public'}}
        self.assertEqual(self.env['_verified_collect_order_link'](invoice)['internalOrderId'],'')
        self.table.get_item.return_value={'Item':{'invoiceId':'inv','invoiceNumber':'N','orderNumber':'public'}}
        self.assertEqual(self.env['_verified_collect_order_link'](invoice)['internalOrderId'],'internal')
        self.table.update_item.assert_not_called()

    def test_delivery_proof_requires_exact_message_contact_image(self):
        invoice={'invoiceId':'inv','customerPhone':'+919000000001','contactId':'saved'}
        logs=[{'invoiceId':'inv','channel':'whatsapp','toNumber':invoice['customerPhone'],'waMessageId':'wamid.exact','imageS3Key':'saved.png','status':'sent'}]
        valid={'direction':'outbound','whatsappMessageId':'wamid.exact','contactId':'saved','s3Key':'saved.png','status':'read','statusUpdatedAt':25}
        for field in ('whatsappMessageId','contactId','s3Key'):
            self.table.query.return_value={'Items':[{**valid,field:'wrong'}]}
            self.assertIn('unverified',self.env['_collect_receipt_delivery'](invoice,logs)['status'])
        self.table.query.return_value={'Items':[{k:v for k,v in valid.items() if k!='s3Key'}]}
        self.assertEqual(self.env['_collect_receipt_delivery'](invoice,logs)['status'],'Read')
        self.table.query.side_effect=RuntimeError('unavailable')
        self.assertIn('unavailable',self.env['_collect_receipt_delivery'](invoice,logs)['status'])
        self.table.update_item.assert_not_called()


if __name__=='__main__':
    unittest.main()
