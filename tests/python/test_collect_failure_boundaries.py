"""Execute invoice-engine boundary statements with in-memory persistence, never AWS.

The large Lambda has import-time clients. AST extraction keeps production control flow
intact while limiting fixtures to the persistence/provider boundary being exercised.
"""
import ast
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from types import SimpleNamespace

import pytest

HANDLER = Path(__file__).resolve().parents[2] / 'amplify/functions/payments/invoice-engine/handler.py'


def boundary(function, start, end, env):
    source = HANDLER.read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function)
    lines = source.splitlines()
    lo = next(i + 1 for i, line in enumerate(lines) if start in line and node.lineno <= i + 1 <= node.end_lineno)
    hi = next(i + 1 for i, line in enumerate(lines) if end in line and lo < i + 1 <= node.end_lineno)
    statements = [n for n in node.body if lo <= n.lineno < hi]
    wrapper = ast.FunctionDef(name='run', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=statements, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    globals_ = {'json': json, 'Decimal': Decimal, 'ROUND_HALF_UP': ROUND_HALF_UP,
                'logger': SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
                '_resp': lambda code, body: {'statusCode': code, 'body': body}, **env}
    exec(compile(module, str(HANDLER), 'exec'), globals_)
    return globals_['run']()


@pytest.mark.parametrize('status,error', [(503, 'DELIVERY_OUTCOME_UNKNOWN'), (500, 'Internal error'), (409, 'MESSAGE_SEND_IN_FLIGHT')])
def test_unknown_downstream_retains_original_send_claim(status, error):
    changes, logs = [], []
    result = boundary('send_payment_link', '    if wa_status_code >= 400:', '    # The attempt advances only', {
        'wa_status_code': status, 'wa_result': {'body': json.dumps({'error': error})},
        'invoice_id': 'inv-1', 'reference_id': 'WD-PAY-ORIGINAL', 'payment_attempt_id': 'attempt-1', 'request_id': 'request-1',
        '_log_delivery': lambda state, **kw: logs.append(state),
        'attempts_table': object(), 'time': SimpleNamespace(time=lambda: 1),
        'wa_payment_request': SimpleNamespace(record_send_rejected=lambda *a, **kw: changes.append('rejected'), release_send_claim=lambda *a, **kw: changes.append('released')),
    })
    assert result['statusCode'] == 202
    assert result['body']['state'] == 'UNCONFIRMED'
    assert result['body']['referenceId'] == 'WD-PAY-ORIGINAL'
    assert changes == []
    assert logs == ['unknown']
    assert 'NOT sent' not in result['body']['error']


def test_claim_loser_cannot_adopt_unfinished_invoice():
    reads = []
    def put(**kwargs):
        raise RuntimeError('conditional conflict')
    def get(**kwargs):
        reads.append(kwargs)
        return {'Item': {'invoiceId': 'inv-1', 'status': 'claiming'}}
    result = boundary('_create_invoice', '    dedup_source = reference_id or payment_id', '    # Auto-generate referenceId', {
        'reference_id': 'WD-PAY-ORIGINAL', 'payment_id': '', 'now': 1, 'claim': {}, 'request_id': 'request-1',
        'table': SimpleNamespace(put_item=put, get_item=get),
        'order_keys': SimpleNamespace(is_conditional_failure=lambda error: True), '_money_display': str,
    })
    assert result is not None
    assert result['statusCode'] == 503
    assert result['body']['errorCode'] == 'INVOICE_CREATE_IN_PROGRESS'
    assert reads[0]['ConsistentRead'] is True
    assert 'invoiceId' not in result['body']


@pytest.mark.parametrize('fail_item', [False, True])
def test_final_invoice_is_published_only_after_all_items(fail_item):
    events = []
    def put_invoice(**kwargs):
        events.append(('invoice',kwargs['Item']))
    def put_item(**kwargs):
        events.append('item')
        if fail_item:
            raise RuntimeError('item write interrupted')
    env = {'invoice': {'invoiceId': 'inv-1','invoiceNumber':'WD/2627/001','referenceId':'WD-PAY-ORIGINAL','total':118,'status':'created'}, 'table': SimpleNamespace(put_item=put_invoice),
           'dynamodb': SimpleNamespace(Table=lambda _: SimpleNamespace(put_item=put_item)),
           'INVOICE_ITEMS_TABLE': 'items', 'items': [{'name': 'Item', 'amount': 100, 'quantity': 1}],
           'body': {}, 'amount_is_tax_inclusive': False, 'gst_rate': Decimal('18'), 'invoice_id': 'inv-1'}
    if fail_item:
        with pytest.raises(RuntimeError, match='item write interrupted'):
            boundary('_create_invoice', '    # Unconditional: the claim above', "    logger.info(json.dumps({'event': 'invoice_created'", env)
        assert events[0][0] == 'invoice'
        staged = events[0][1]
        assert staged['status'] == 'claiming'
        assert staged['invoiceNumber'] == 'WD/2627/001'
        assert staged['referenceId'] == 'WD-PAY-ORIGINAL'
        assert staged['total'] == 118
        assert staged['expectedItemCount'] == 1
        assert events[1:] == ['item']
    else:
        boundary('_create_invoice', '    # Unconditional: the claim above', "    logger.info(json.dumps({'event': 'invoice_created'", env)
        assert events[0][1]['status'] == 'claiming'
        assert events[1] == 'item'
        assert events[2][1]['status'] == 'created'
        assert events[0][1]['invoiceNumber'] == events[2][1]['invoiceNumber']


def test_unfinished_invoice_cannot_send_payment():
    result = boundary('send_payment_link', '    table = dynamodb.Table(INVOICES_TABLE)', "    customer_phone = invoice.get('customerPhone'", {
        'invoice_id': 'inv-1', 'INVOICES_TABLE': 'invoices',
        'dynamodb': SimpleNamespace(Table=lambda _: SimpleNamespace(get_item=lambda **kw: {'Item': {'status': 'claiming'}})),
        'pay_status': SimpleNamespace(rank=lambda _: 0, STATUS_RANK={'captured': 2}, CAPTURED='captured'),
    })
    assert result is not None
    assert result['statusCode'] == 503
    assert result['body']['errorCode'] == 'INVOICE_CREATE_IN_PROGRESS'


@pytest.mark.parametrize('status,error,expected_change,expected_status', [
    (400, 'INVALID_REQUEST', 'released', 502),
    (409, 'PAYMENT_CONFIGURATION_UNAVAILABLE', 'rejected', 409),
])
def test_proven_pre_send_refusal_keeps_explicit_rejection(status, error, expected_change, expected_status):
    changes, logs = [], []
    result = boundary('send_payment_link', '    if wa_status_code >= 400:', '    # The attempt advances only', {
        'wa_status_code': status, 'wa_result': {'body': {'error': error}},
        'invoice_id': 'inv-1', 'reference_id': 'WD-PAY-ORIGINAL', 'payment_attempt_id': 'attempt-1', 'request_id': 'request-1',
        '_log_delivery': lambda state, **kw: logs.append(state),
        'attempts_table': object(), 'time': SimpleNamespace(time=lambda: 1),
        'wa_payment_request': SimpleNamespace(record_send_rejected=lambda *a, **kw: changes.append('rejected'), release_send_claim=lambda *a, **kw: changes.append('released')),
    })
    assert result['statusCode'] == expected_status
    assert result['body']['sendStatus'] == 'REJECTED'
    assert changes == [expected_change]
    assert logs == ['rejected']


def test_claim_loser_adopts_completed_invoice_without_another_number():
    def put(**kwargs):
        raise RuntimeError('conditional conflict')
    result = boundary('_create_invoice', '    dedup_source = reference_id or payment_id', '    # Auto-generate referenceId', {
        'reference_id': 'WD-PAY-ORIGINAL', 'payment_id': '', 'now': 1, 'claim': {}, 'request_id': 'request-1',
        'table': SimpleNamespace(put_item=put, get_item=lambda **kw: {'Item': {'invoiceNumber': 'WD/2627/001', 'status': 'created', 'total': 100}}),
        'order_keys': SimpleNamespace(is_conditional_failure=lambda error: True), '_money_display': str,
    })
    assert result['statusCode'] == 200
    assert result['body']['invoiceNumber'] == 'WD/2627/001'
    assert result['body']['deduplicated'] is True


def outbound_boundary(response, raw):
    """Execute the real invoke/acceptance boundary, ending before invoice projection."""
    import io
    tree = ast.parse(HANDLER.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'send_payment_link')
    start = next(i for i,n in enumerate(function.body) if isinstance(n, ast.Try) and any(isinstance(child,ast.Call) and isinstance(child.func,ast.Attribute) and isinstance(child.func.value,ast.Name) and child.func.value.id=='lambda_client' and child.func.attr=='invoke' for child in ast.walk(n)))
    end = next(i for i,n in enumerate(function.body) if i>start and isinstance(n,ast.Try) and any(isinstance(child,ast.Call) and isinstance(child.func,ast.Attribute) and child.func.attr=='update_item' for child in ast.walk(n)))
    wrapper = ast.FunctionDef(name='run',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=function.body[start:end],decorator_list=[])
    changes,logs=[],[]
    env={'json':json,'wa_payload':{},'reference_id':'WD-PAY-ORIGINAL','invoice_id':'inv-1','request_id':'request-1','payment_attempt_id':'attempt-1','attempts_table':object(),
         'lambda_client':SimpleNamespace(invoke=lambda **kw:{**response,'Payload':io.BytesIO(raw.encode())}),
         '_resp':lambda code,body:{'statusCode':code,'body':body},'_log_delivery':lambda state,**kw:logs.append((state,kw)),
         'logger':SimpleNamespace(error=lambda *a:None), 'time':SimpleNamespace(time=lambda:1),
         'wa_payment_request':SimpleNamespace(record_sent=lambda *a,**kw:changes.append('sent'),record_send_rejected=lambda *a,**kw:changes.append('rejected'),release_send_claim=lambda *a,**kw:changes.append('released'))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[])),str(HANDLER),'exec'),env)
    result=env['run']()
    return result,changes,logs


@pytest.mark.parametrize('response,raw',[
    ({'StatusCode':200,'FunctionError':'Unhandled'},'{"errorMessage":"crashed"}'),
    ({'StatusCode':200},'{}'),
    ({'StatusCode':200},'[]'),
    ({'StatusCode':200},'invalid JSON'),
    ({'StatusCode':200},'{"statusCode":200,"body":{}}'),
    ({'StatusCode':200},'{"statusCode":202,"body":"not JSON"}'),
    ({'StatusCode':200},'{"statusCode":200,"body":{"messageId":"internal-id"}}'),
    ({'StatusCode':200},'{"statusCode":202,"body":{"whatsappMessageId":"wamid.cached","sendUnconfirmed":true}}'),
    ({'StatusCode':200},'{"statusCode":202,"body":{"whatsappMessageId":"wamid.cached","status":"DELIVERY_OUTCOME_UNKNOWN"}}'),
    ({'StatusCode':200},'{"statusCode":200,"body":{"whatsappMessageId":"wamid.cached","error":"UNKNOWN"}}'),
])
def test_transport_success_without_provider_acceptance_never_records_sent(response,raw):
    result,changes,logs=outbound_boundary(response,raw)
    assert result is not None
    assert result['body']['sendStatus']=='PENDING'
    assert changes==[]
    assert logs[0][0]=='unknown'


@pytest.mark.parametrize('status,key',[(200,'whatsappMessageId'),(202,'messageId')])
def test_provider_acceptance_advances_original_attempt(status,key):
    result,changes,logs=outbound_boundary({'StatusCode':200},json.dumps({'statusCode':status,'body':json.dumps({key:'wamid.accepted'})}))
    assert result is None  # Continues to invoice projection only after proven acceptance.
    assert changes==['sent']
    assert logs==[]


def test_scan_dedup_cannot_adopt_staged_numbered_invoice():
    result = boundary('_create_invoice', '    if reference_id or payment_id:', '    # ── Atomic claim', {
        'reference_id':'WD-PAY-ORIGINAL', 'payment_id':'', 'request_id':'request-1', 'body':{}, 'now':1,
        'table':SimpleNamespace(scan=lambda **kw:{'Items':[{'invoiceId':'inv-1','invoiceNumber':'WD/2627/001','referenceId':'WD-PAY-ORIGINAL','status':'claiming','total':118}]}),
        '_money_display':str,
    })
    assert result['statusCode']==503
    assert result['body']['errorCode']=='INVOICE_CREATE_IN_PROGRESS'
    assert 'invoiceId' not in result['body']
