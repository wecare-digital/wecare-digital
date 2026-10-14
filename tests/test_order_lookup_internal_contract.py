"""Order lookup must use IAM invocation context, never a browser Origin.

Wix exit: `fetch_orders_for_flow` no longer falls back to the `wecare-wix-store`
Lambda (deleted in the Wix exit) — OrdersTable is the sole source. The remaining
contract this file guards is the invocation-auth rule: an internal (IAM) invoke
has no API Gateway `apiId` and is accepted; a call carrying a gateway `apiId` is
rejected 401. That rule is independent of where orders are read from, so it is
asserted directly against a synthetic internal event rather than captured from a
Wix invoke that no longer happens.
"""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def test_flow_lookup_reads_only_orders_table_no_wix_fallback():
    """The Wix Store Lambda fallback is gone; lookup returns from OrdersTable alone."""
    path = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/orders.py'
    spec = importlib.util.spec_from_file_location('order_lookup_contract', path)
    orders = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(orders)
    orders.dynamodb.Table.return_value.query.return_value = {'Items': []}
    # No wix-store invoke path remains: an empty OrdersTable yields an empty result,
    # with no external Lambda call to fall back to.
    assert orders.fetch_orders_for_flow('', 'customer@example.test') == []
    assert not hasattr(orders, 'lambda_client'), (
        'the wecare-wix-store invoke client must be gone after the Wix exit')


def test_internal_context_accepted_gateway_rejected():
    """IAM-internal invoke (no apiId) is accepted; a gateway apiId is rejected 401."""
    event = {
        'rawPath': '/service/orders',
        'queryStringParameters': {'email': 'customer@example.test'},
        'headers': {},
        'requestContext': {'http': {'method': 'GET'}},
    }
    assert 'origin' not in event.get('headers', {})

    from lambda_utils.middleware import require_auth
    with patch('lambda_utils.middleware.cognito') as cognito:
        assert require_auth(event) is None
        cognito.get_user.assert_not_called()
        event['requestContext']['apiId'] = 'gateway-test'
        response = require_auth(event)
        assert response['statusCode'] == 401
        cognito.get_user.assert_not_called()
