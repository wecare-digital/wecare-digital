"""Regression checks for private staff downloads and bounded customer commands."""
import ast
import copy
import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest
from lambda_utils import media_paths
ROOT = Path(os.environ.get('REVIEW_SOURCE', Path(__file__).resolve().parents[1]))


def commands():
    path = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py'
    spec = importlib.util.spec_from_file_location('bounded_customer_commands', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Orders:
    def __init__(self):
        self.calls = []
    def query(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        limit = kwargs['Limit']
        return {'Items': [{'orderNumber': str(i).zfill(2) + 'x' * 78} for i in range(limit)],
                'LastEvaluatedKey': {'id': str(len(self.calls))}}


@pytest.mark.parametrize('page', [1, 9, 10])
def test_orders_cta_fits_provider_body_without_silently_skipping_rows(page):
    table = Orders()
    text = commands().reply(table, {}, SimpleNamespace(customer_id='fixture'), ('orders', page))
    assert len(text) <= 1024
    assert len(table.calls) == page
    assert all(c['Limit'] == 10 for c in table.calls)
    assert all(c['ExpressionAttributeValues'] == {':owner': 'fixture'} for c in table.calls)
    for i in range(10):
        assert str(i).zfill(2) + 'x' * 78 in text
    if page < 10:
        assert f'Orders page {page + 1}' in text
    else:
        assert 'Orders page 11' not in text
        assert 'view further orders' in text


@pytest.mark.parametrize('page', [11, 999])
def test_large_customer_page_redirects_to_verified_account_without_ddb_walk(page):
    table = Orders()
    module = commands()
    selected = module.command(f'Orders page {page}')
    assert selected == ('orders', page)
    text = module.reply(table, {}, SimpleNamespace(customer_id='fixture'), selected)
    assert table.calls == []
    assert module.ORDERS_URL in text and 'further orders' in text


@pytest.mark.parametrize('page', [0, 11, 999, True, '1'])
def test_direct_order_page_cannot_bypass_read_budget(page):
    table = Orders()
    with pytest.raises(ValueError):
        commands().order_page(table, 'fixture', page)
    assert table.calls == []


def staff_response(record, signer):
    path = ROOT / 'amplify/functions/messaging/whatsapp-business-api/handler.py'
    tree = ast.parse(path.read_text())
    names = {'_project_submission_attachments', '_list_flow_submissions'}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    class Table:
        def scan(self, **kwargs):
            return {'Items': [record]}
    logs = []
    ns = {'dynamodb': SimpleNamespace(Table=lambda name: Table()), 'FLOW_SUBMISSIONS_TABLE': 'fixture',
          'Decimal': Decimal, 'Dict': dict, 'json': json, 'media_paths': media_paths,
          's3_client': SimpleNamespace(generate_presigned_url=signer), 'MEDIA_BUCKET': 'fixture-media',
          '_resp': lambda status, body: body,
          'logger': SimpleNamespace(error=logs.append, warning=logs.append)}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), ns)
    return ns['_list_flow_submissions']({}), logs


def test_staff_private_download_is_response_only_short_lived_and_never_logged():
    record = {'createdAt': 1, 'attachments': [{'key': 'secure/u/service-requests/fixture/document.pdf', 'private': True}]}
    original = copy.deepcopy(record)
    calls = []
    def signer(*args, **kwargs):
        calls.append((args, kwargs))
        return 'https://fixture.invalid/bearer-token'
    response, logs = staff_response(record, signer)
    assert response['submissions'][0]['attachments'][0]['url'] == 'https://fixture.invalid/bearer-token'
    assert calls == [(('get_object',), {'Params': {'Bucket': 'fixture-media', 'Key': original['attachments'][0]['key']}, 'ExpiresIn': 300})]
    assert record == original
    assert logs == []


@pytest.mark.parametrize('key', ['secure/d/other/document.pdf', 'secure/u/service-requests/../other.pdf',
                               'secure/u/service-requests//other.pdf', 'secure/u/service-requests/fixture\\other.pdf'])
def test_staff_attachment_signing_rejects_unrelated_or_unsafe_private_keys(key):
    record = {'createdAt': 1, 'attachments': [{'key': key, 'url': 'stale-bearer', 'link': 'stale-bearer'}]}
    def signer(*args, **kwargs):
        pytest.fail('Unsafe attachment must not be signed')
    response, logs = staff_response(record, signer)
    entry = response['submissions'][0]['attachments'][0]
    assert 'url' not in entry and 'link' not in entry
    assert record['attachments'][0]['url'] == 'stale-bearer'


def test_staff_signing_failure_does_not_leak_error_contents_or_restore_public_link():
    record = {'createdAt': 1, 'attachments': [{'key': 'secure/u/whatsapp/incoming/fixture.pdf'}]}
    def signer(*args, **kwargs):
        raise RuntimeError('private-payload-secret')
    response, logs = staff_response(record, signer)
    assert 'url' not in response['submissions'][0]['attachments'][0]
    assert 'private-payload-secret' not in str(logs)
    assert 'RuntimeError' in str(logs)


def test_legacy_public_and_string_attachments_remain_unchanged_without_signing():
    record = {'createdAt': 1, 'attachments': ['https://fixture.invalid/public', {'key': 'o/legacy.pdf', 'url': 'public-link'}]}
    def signer(*args, **kwargs):
        pytest.fail('Public attachment must not be signed')
    response, logs = staff_response(record, signer)
    assert response['submissions'][0]['attachments'] == record['attachments']
