"""Customer coupon auth exercises the real session policy and DynamoDB adapter."""
import importlib.util
import pathlib
import time
from unittest.mock import MagicMock
import pytest
from lambda_utils import customer_session as sessions


def _handler():
    path = pathlib.Path(__file__).resolve().parents[1] / 'amplify/functions/ecommerce/coupons/handler.py'
    spec = importlib.util.spec_from_file_location('coupon_runtime_auth', path)
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    return handler


@pytest.mark.parametrize('csrf,accepted', [('fixture-csrf', True), ('wrong', False), ('', False)])
def test_customer_session_adapter_and_csrf_before_coupon_mutation(monkeypatch, csrf, accepted):
    handler = _handler()
    table = MagicMock()
    now = int(time.time())
    table.get_item.return_value = {'Item': {
        'sidHash': 'fixture-hash', 'customerId': 'owner-fixture', 'csrfToken': 'fixture-csrf',
        'absoluteExpiresAt': now + 3600, 'idleExpiresAt': now + 3600,
        'persistent': True,
    }}
    monkeypatch.setattr(handler, '_table', lambda _: table)
    monkeypatch.setattr(sessions, 'read_cookie', lambda _: 'fixture-session')
    event = {'headers': {'x-customer-csrf': csrf}}
    if accepted:
        assert handler._customer(event).customer_id == 'owner-fixture'
    else:
        with pytest.raises(handler.Refused) as rejected:
            handler._customer(event)
        assert rejected.value.status == 401
    table.get_item.assert_called_once()
    table.update_item.assert_called_once()
