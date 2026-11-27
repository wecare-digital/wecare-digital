"""Authorization progress and failures produce explicit, non-sensitive outcomes."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE = Path(__file__).resolve().parents[2] / 'amplify/functions/ai/customer-commerce-mcp'


@pytest.fixture
def auth(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE))
    monkeypatch.setenv('CUSTOMER_COMMERCE_ORIGIN', 'https://example.execute-api.us-east-1.amazonaws.com')
    return importlib.import_module('customer_oauth_authorize')


@pytest.mark.parametrize('message,outcome', [
    ('New code sent.', 'code_sent'),
    ('Account ready. Enter the new code.', 'code_sent'),
    ('Number verified. Get a new code.', 'retry_code'),
    ('Could not resend the code. Try again.', 'error'),
    ('', ''),
])
def test_pending_state_has_structured_outcome(auth, monkeypatch, message, outcome):
    web = importlib.import_module('customer_oauth_web')
    monkeypatch.setattr(web, 'uncapsule', lambda *args: {'phase': 'code'})
    row = {'kind': 'web-auth', 'client': 'wecare-website', 'sidHash': 'fixture', 'cipher': 'fixture', 'return': '/orders/'}
    reply = json.loads(web.auth_state(row, 'csrf', message)['body'])
    assert reply['outcome'] == outcome
    assert reply['phase'] == 'code'
    assert reply['returnPath'] == '/orders/'


def prepare(auth, monkeypatch, phase):
    login = {'phase': phase, 'phone': '+919000000000', 'session': 'fixture'}
    row = {'kind': 'web-auth', 'client': 'wecare-website', 'sidHash': 'fixture', 'cipher': 'fixture', 'csrfHash': auth.digest('csrf')}
    monkeypatch.setattr(auth, '_cookie_row', lambda _: ('fixture', row))
    monkeypatch.setattr(auth, 'uncapsule', lambda *args: login)
    monkeypatch.setattr(auth, 'STORE', SimpleNamespace(take=lambda _: row))
    monkeypatch.setattr(auth, 'save_pending', lambda row, login, message='': {'phase': login['phase'], 'message': message})
    return {'csrf': 'csrf', '_flow': 'website'}, {'headers': {'origin': 'https://wecare.digital'}}


def test_failed_registration_resend_is_not_silent(auth, monkeypatch):
    params, event = prepare(auth, monkeypatch, 'registration')
    monkeypatch.setattr(auth, 'registration_call', lambda *args: False)
    reply = auth.authorize_post({**params, 'action': 'resend'}, event)
    assert reply == {'phase': 'registration', 'message': 'Could not resend the code. Try again.'}


def test_provider_failure_is_retryable_without_leaking_details(auth, monkeypatch):
    params, event = prepare(auth, monkeypatch, 'code')
    def unavailable(*args):
        raise RuntimeError('private provider details')
    monkeypatch.setattr(auth, 'aws', unavailable)
    reply = auth.authorize_post({**params, 'code': '123456'}, event)
    assert reply == {'phase': 'code', 'message': 'Could not complete sign-in. Try again.'}


def test_registration_still_requires_cognito_challenge(auth, monkeypatch):
    params, event = prepare(auth, monkeypatch, 'registration')
    monkeypatch.setattr(auth, 'registration_call', lambda *args: True)
    monkeypatch.setattr(auth, 'aws', lambda _: SimpleNamespace(initiate_auth=lambda **kwargs: {'Session': 'new-challenge'}))
    reply = auth.authorize_post({**params, 'code': '123456'}, event)
    assert reply == {'phase': 'code', 'message': 'Account ready. Enter the new code.'}
