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
        names = {'_verified_collect_order_link', '_collect_receipt_delivery'}
        tree = ast.parse(source)
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.table = Mock()
        self.env = {'Dict':dict, 'List':list, 're':__import__('re'), 'os':__import__('os'),
                    'dynamodb':SimpleNamespace(Table=lambda _:self.table),
                    'shared_tables':SimpleNamespace(orders_table_name=lambda:'orders'),
                    'logger':Mock(), 'boto3':SimpleNamespace(dynamodb=SimpleNamespace(conditions=SimpleNamespace(Key=lambda _:SimpleNamespace(eq=lambda _:True))))}
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<isolated projection>', 'exec'),self.env)

    def test_order_link_requires_reciprocal_invoice(self):
        invoice={'invoiceId':'inv','invoiceNumber':'N','internalOrderId':'internal','orderNumber':'public'}
        self.table.get_item.return_value={'Item':{'invoiceId':'different','invoiceNumber':'N','orderNumber':'public'}}
        self.assertEqual(self.env['_verified_collect_order_link'](invoice)['internalOrderId'],'')
        self.table.get_item.return_value={'Item':{'invoiceId':'inv','invoiceNumber':'N','orderNumber':'public'}}
        self.assertEqual(self.env['_verified_collect_order_link'](invoice)['internalOrderId'],'internal')
        self.table.update_item.assert_not_called()

    def test_delivery_proof_requires_exact_message_contact_image(self):
        invoice={'customerPhone':'+919000000001','contactId':'saved'}
        logs=[{'channel':'whatsapp','toNumber':invoice['customerPhone'],'waMessageId':'wamid.exact','imageS3Key':'saved.png','status':'sent'}]
        valid={'whatsappMessageId':'wamid.exact','contactId':'saved','s3Key':'saved.png','status':'read','statusUpdatedAt':25}
        for field in ('whatsappMessageId','contactId','s3Key'):
            self.table.query.return_value={'Items':[{**valid,field:'wrong'}]}
            self.assertIn('unverified',self.env['_collect_receipt_delivery'](invoice,logs)['status'])
        self.table.query.return_value={'Items':[valid]}
        self.assertEqual(self.env['_collect_receipt_delivery'](invoice,logs)['status'],'Read')
        self.table.query.side_effect=RuntimeError('unavailable')
        self.assertIn('unavailable',self.env['_collect_receipt_delivery'](invoice,logs)['status'])
        self.table.update_item.assert_not_called()


if __name__=='__main__':
    unittest.main()
