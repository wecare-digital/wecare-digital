"""Staff customer creation must finish account provisioning and ownership linking."""
import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUB = '940844d8-c031-70cf-4398-f1a58831231b'
PHONE = '+919000000001'


def load(path, name, **env):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'Dict': dict, 'Any': object, 'Tuple': tuple, 'json': json,
             'time': SimpleNamespace(time=lambda: 1800000000), **env}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
    return scope[name]


class Table:
    def __init__(self, **changes):
        self.row = {'id': 'contact-1', 'phone': PHONE, **changes}
        self.writes = []

    def get_item(self, **kwargs):
        return {'Item': dict(self.row)}

    def update_item(self, **kwargs):
        self.writes.append(kwargs)
        self.row['checkoutCustomerId'] = kwargs['ExpressionAttributeValues'][':sub']
        return {'Attributes': dict(self.row)}


def provisioner(table, answer=None, function_error=False):
    calls = []
    answer = answer or {'outcome': 'CUSTOMER_IDENTITY_READY', 'customerId': SUB, 'phone': PHONE}
    def invoke(**kwargs):
        calls.append(kwargs)
        return {'StatusCode': 200, **({'FunctionError': 'Unhandled'} if function_error else {}),
                'Payload': io.BytesIO(json.dumps(answer).encode())}
    fn = load('amplify/functions/core/contacts/handler.py', '_provision_customer_login',
              _lambda_client=SimpleNamespace(invoke=invoke),
              dynamodb=SimpleNamespace(Table=lambda _: table), CONTACTS_TABLE='contacts',
              CUSTOMER_LOGIN_FUNCTION='secure-files:live',
              customer_auth=SimpleNamespace(is_cognito_subject=lambda s: s == SUB),
              contact_key=SimpleNamespace(key=lambda x: {'id': x}),
              log_event=lambda *a, **k: None, logger=None)
    return fn, calls


def test_staff_provision_is_synchronous_and_returns_linked_contact():
    table = Table()
    fn, calls = provisioner(table)
    result = fn(PHONE, 'request-1', contact_id='contact-1', actor='staff-1')
    assert result['checkoutCustomerId'] == SUB
    assert calls[0]['InvocationType'] == 'RequestResponse'
    assert json.loads(calls[0]['Payload'])['internalAction'] == 'provisionCustomerIdentity'
    write = table.writes[0]
    assert ':sub' in write['ConditionExpression']
    assert ':phone' in write['ConditionExpression']
    assert write['ExpressionAttributeValues'][':actor'] == 'staff-1'


@pytest.mark.parametrize('changes', [{'checkoutCustomerId': 'another-owner'}, {'isDeleted': True},
                                    {'mergedIntoContactId': 'other-contact'}, {'phone': '+919000000002'}])
def test_staff_provision_never_reassigns_or_revives_a_conflicting_contact(changes):
    table = Table(**changes)
    fn, _ = provisioner(table)
    with pytest.raises(ValueError):
        fn(PHONE, 'request-1', contact_id='contact-1', actor='staff-1')
    assert not table.writes


@pytest.mark.parametrize('answer,function_error', [({}, True),
    ({'outcome': 'CUSTOMER_IDENTITY_READY', 'customerId': SUB, 'phone': '+919000000002'}, False),
    ({'outcome': 'CUSTOMER_IDENTITY_NOT_READY'}, False)])
def test_uncertain_or_wrong_account_cannot_be_linked(answer, function_error):
    table = Table()
    fn, _ = provisioner(table, answer, function_error)
    with pytest.raises(ValueError):
        fn(PHONE, 'request-1', contact_id='contact-1', actor='staff-1')
    assert not table.writes


@pytest.mark.parametrize('enabled,verified,expected', [(True, 'true', 'CUSTOMER_IDENTITY_READY'),
    (False, 'true', 'CUSTOMER_IDENTITY_NOT_READY'), (True, 'false', 'CUSTOMER_IDENTITY_NOT_READY')])
def test_secure_files_returns_only_an_enabled_matching_confirmed_account(enabled, verified, expected):
    user = {'Enabled': enabled, 'UserStatus': 'CONFIRMED', 'UserAttributes': [
        {'Name': 'sub', 'Value': SUB}, {'Name': 'phone_number', 'Value': PHONE},
        {'Name': 'phone_number_verified', 'Value': verified}]}
    fn = load('amplify/functions/core/secure-files/handler.py', 'provision_customer_identity',
              provision_customer_login=lambda _: (True, 'provisioned'),
              _cognito_client=lambda: SimpleNamespace(admin_get_user=lambda **k: user),
              CUSTOMER_POOL_ID='customer-pool',
              customer_auth=SimpleNamespace(is_cognito_subject=lambda s: s == SUB),
              logger=SimpleNamespace(warning=lambda *a: None))
    assert fn(PHONE)['outcome'] == expected


@pytest.mark.parametrize('failure', [ValueError('CUSTOMER_IDENTITY_NOT_READY'), RuntimeError('timeout')])
def test_partial_account_failure_returns_retained_contact_and_safe_retry(failure):
    table = Table()
    def provision(*a, **k):
        raise failure
    fn = load('amplify/functions/core/contacts/handler.py', '_complete_customer_identity',
              dynamodb=SimpleNamespace(Table=lambda _: table), CONTACTS_TABLE='contacts',
              contact_key=SimpleNamespace(key=lambda x: {'id': x}),
              _e164_or_error=lambda p: (p, None), _check_duplicate=lambda *a, **k: None,
              _provision_customer_login=provision, _from_dynamo=lambda x: x,
              cors_response=lambda status, body, origin: {'statusCode': status, 'body': body},
              log_event=lambda *a, **k: None, logger=None)
    result = fn('contact-1', 'request-1', '', 'staff-1', success_status=201)
    assert result['statusCode'] == 503
    assert result['body']['contactCreated'] is True
    assert result['body']['contactId'] == 'contact-1'
    assert result['body']['retryAction'] == 'provision_customer_identity'


def test_complete_identity_returns_success_only_with_the_linked_record():
    table = Table()
    linked = {**table.row, 'checkoutCustomerId': SUB}
    fn = load('amplify/functions/core/contacts/handler.py', '_complete_customer_identity',
              dynamodb=SimpleNamespace(Table=lambda _: table), CONTACTS_TABLE='contacts',
              contact_key=SimpleNamespace(key=lambda x: {'id': x}),
              _e164_or_error=lambda p: (p, None), _check_duplicate=lambda *a, **k: None,
              _provision_customer_login=lambda *a, **k: linked, _from_dynamo=lambda x: x,
              cors_response=lambda status, body, origin: {'statusCode': status, 'body': body})
    result = fn('contact-1', 'request-1', '', 'staff-1', success_status=201)
    assert result['statusCode'] == 201
    assert result['body']['checkoutCustomerId'] == SUB


def test_staff_retry_resumes_an_interrupted_cognito_password_confirmation():
    attrs = [{'Name': 'sub', 'Value': SUB}, {'Name': 'phone_number', 'Value': PHONE},
             {'Name': 'phone_number_verified', 'Value': 'true'}]
    user = {'Enabled': True, 'UserStatus': 'FORCE_CHANGE_PASSWORD', 'UserAttributes': attrs}
    calls = []
    def confirm(**kwargs):
        calls.append(kwargs)
        user['UserStatus'] = 'CONFIRMED'
    client = SimpleNamespace(admin_get_user=lambda **k: dict(user), admin_set_user_password=confirm)
    fn = load('amplify/functions/core/secure-files/handler.py', 'provision_customer_identity',
              provision_customer_login=lambda _: (True, 'exists'), _cognito_client=lambda: client,
              CUSTOMER_POOL_ID='customer-pool', pysecrets=SimpleNamespace(token_urlsafe=lambda _: 'random-secret'),
              customer_auth=SimpleNamespace(is_cognito_subject=lambda s: s == SUB),
              logger=SimpleNamespace(warning=lambda *a: None))
    result = fn(PHONE)
    assert result['outcome'] == 'CUSTOMER_IDENTITY_READY'
    assert calls[0]['Permanent'] is True
    assert 'random-secret' not in json.dumps(result)
