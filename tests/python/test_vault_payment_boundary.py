"""Execute checkout boundary functions with offline provider stubs; never contact AWS."""
import ast
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from lambda_utils.ecommerce import order_delivery, payment_address, service_requests
from lambda_utils.identity import customer as customer_identity

HANDLER = Path(__file__).resolve().parents[2] / 'amplify/functions/ecommerce/checkout/handler.py'
ADDRESS = {'addressLine1': 'Example street', 'city': 'Kolkata', 'state': 'West Bengal',
           'postalCode': '700012', 'countryCode': 'IN'}


def function(name, **extra):
    node = next(n for n in ast.parse(HANDLER.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    env = {'Dict': dict, 'Any': object, 'Optional': __import__('typing').Optional,
           'json': json, 'order_delivery': order_delivery, 'customer_identity': customer_identity,
           **extra}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HANDLER), 'exec'), env)
    return env[name]


def send(result=None, *, error=None, function_error=False, raw=None):
    def invoke(**kwargs):
        if error:
            raise error
        return {'Payload': io.BytesIO(raw if raw is not None else json.dumps(result).encode()),
                **({'FunctionError': 'Unhandled'} if function_error else {})}
    fn = function('_send_order_details', _outbound_send_client=lambda: SimpleNamespace(invoke=invoke),
        OUTBOUND_SENDER_FUNCTION='offline', whatsapp_templates=SimpleNamespace(PAY=SimpleNamespace(name='pay')),
        SEND_SENT='SENT', SEND_FAILED='FAILED', SEND_UNCONFIRMED='UNCONFIRMED', logger=logging.getLogger(__name__))
    return fn(phone='+919000000001', contact_id='contact', phone_number_id='sender',
              order_details={'reference_id': 'offline-reference'})


@pytest.mark.parametrize('result', [
    {'statusCode': 500, 'body': '{}'},
    {'statusCode': 503, 'body': '{}'},
    {'statusCode': 409, 'body': json.dumps({'error': 'MESSAGE_SEND_IN_FLIGHT'})},
])
def test_ambiguous_sender_responses_keep_the_payment_in_flight(result):
    assert send(result) == 'UNCONFIRMED'


def test_sender_crash_after_acceptance_is_ambiguous_even_without_timeout_text():
    assert send({'errorMessage': 'post-send processing failed'}, function_error=True) == 'UNCONFIRMED'


def test_response_decode_failure_after_invoke_is_ambiguous():
    assert send(raw=b'provider-response-not-json') == 'UNCONFIRMED'


@pytest.mark.parametrize('code', [400, 401, 403, 422, 429])
def test_definite_sender_rejections_are_not_reported_as_sent(code):
    assert send({'statusCode': code, 'body': json.dumps({'error': 'REFUSED'})}) == 'FAILED'


def test_confirmed_send_is_still_sent():
    assert send({'statusCode': 200, 'body': json.dumps({'whatsappMessageId': 'wamid.offline'})}) == 'SENT'


def test_actual_shipping_builder_includes_canonical_phone():
    shipping = function('_payment_shipping_info')(
        {'name': 'Example Customer', 'phone': '+91 90000 00001'}, ADDRESS)
    assert shipping['addresses'][0]['phone_number'] == '919000000001'


@pytest.mark.parametrize('phone', [None, '', 'not-a-phone', '9000000001'])
def test_shipping_builder_refuses_missing_or_invalid_phone(phone):
    with pytest.raises(customer_identity.InvalidPhoneNumber):
        function('_payment_shipping_info')({'name': 'Example Customer', 'phone': phone}, ADDRESS)


@pytest.mark.parametrize('phone', [None, '', 'not-a-phone'])
def test_missing_shipping_phone_fails_before_quote_or_payment_reservation(phone):
    def forbidden(*args, **kwargs):
        pytest.fail('must refuse missing phone before quoting or reserving payment')
    fn = function('_create', customer_auth=SimpleNamespace(CustomerIdentity=object),
        short_purchase=SimpleNamespace(enabled=lambda: False),
        service_requests=SimpleNamespace(VAULT='VAULT', checkout_preflight=lambda *a, **kw: None),
        contact_address=SimpleNamespace(from_contact=lambda p: ADDRESS), payment_address=payment_address,
        _payment_shipping_info=function('_payment_shipping_info'),
        _native_quote=forbidden, time=__import__('time'),
        catalog_pricing=SimpleNamespace(CatalogPricingError=ValueError),
        cors_response=lambda status, body, origin: {'statusCode': status, 'body': body})
    response = fn(SimpleNamespace(phone='+919000000001'), {'lineItems': [{'quantity': 1}]}, '',
                  catalog_session={'kind': 'VAULT'},
                  native_contact={'name': 'Example Customer', 'phone': phone})
    assert response['statusCode'] == 409
    assert response['body']['error'] == 'DELIVERY_DETAILS_REQUIRED'


@pytest.mark.parametrize('code', ['AccessDeniedException', 'ResourceNotFoundException',
                                  'TooManyRequestsException', 'InvalidParameterValueException'])
def test_explicit_aws_invocation_refusals_are_definitely_unsent(code):
    from botocore.exceptions import ClientError
    assert send(error=ClientError({'Error': {'Code': code}}, 'Invoke')) == 'FAILED'


def test_unknown_aws_failure_is_ambiguous():
    from botocore.exceptions import ClientError
    assert send(error=ClientError({'Error': {'Code': 'ServiceException'}}, 'Invoke')) == 'UNCONFIRMED'


@pytest.mark.parametrize('result', [None, {}, {'statusCode': 0},
    {'statusCode': 409, 'body': 'not-json'}, {'statusCode': 500, 'body': 'not-json'}])
def test_malformed_or_missing_sender_response_is_ambiguous(result):
    assert send(result) == 'UNCONFIRMED'


@pytest.mark.parametrize('body', [
    {}, {'status': 'sent'}, {'messageId': 'local-message-id'},
    {'error': 'DELIVERY_OUTCOME_UNKNOWN'},
    {'error': 'DELIVERY_OUTCOME_UNKNOWN', 'whatsappMessageId': 'wamid.offline'},
    {'status': 'DELIVERY_OUTCOME_UNKNOWN', 'whatsappMessageId': 'wamid.offline'},
    {'mode': 'DRY_RUN', 'whatsappMessageId': 'wamid.offline'},
    {'sendUnconfirmed': True, 'whatsappMessageId': 'wamid.offline'},
])
@pytest.mark.parametrize('code', [200, 202])
def test_success_http_without_provider_acceptance_is_ambiguous(code, body):
    assert send({'statusCode': code, 'body': json.dumps(body)}) == 'UNCONFIRMED'


@pytest.mark.parametrize('body', [
    {'whatsappMessageId': 'wamid.offline', 'messageId': 'local-message-id'},
    {'messageId': 'wamid.offline'},
    {'success': True, 'messageId': 'local-message-id',
     'whatsappMessageId': 'wamid.offline', 'mode': 'LIVE', 'idempotent': True},
])
def test_actual_and_cached_meta_acceptance_are_sent(body):
    assert send({'statusCode': 200, 'body': json.dumps(body)}) == 'SENT'
