"""Order lookup must use IAM invocation context, never a browser Origin."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def test_the_whatsapp_flow_order_lookup_no_longer_calls_wix():
    """The WhatsApp Flow order lookup is AWS-NATIVE: it reads OrdersTable and makes no Wix call.

    `refactor(orders): remove Wix fallback from WhatsApp lookup` dropped the `/wix-store/orders`
    Lambda round-trip, so with an empty OrdersTable result the lookup returns [] without invoking
    any Lambda. This pins that the Wix fallback stays gone - a reintroduced `lambda_client.invoke`
    on this path is exactly the regression to catch."""
    path = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/orders.py'
    spec = importlib.util.spec_from_file_location('order_lookup_contract', path)
    orders = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(orders)
    orders.dynamodb.Table.return_value.query.return_value = {'Items': []}
    orders.lambda_client = MagicMock()

    assert orders.fetch_orders_for_flow('', 'customer@example.test') == []
    # The Wix fallback is gone: no Lambda invoke on this path anymore.
    orders.lambda_client.invoke.assert_not_called()


def test_internal_lambda_context_skips_auth_while_a_gateway_context_is_enforced():
    """The order lookup runs Lambda-to-Lambda (no API Gateway request context), and `require_auth`
    treats any event lacking an apiId as an internal call it must not 401. An event that DOES carry
    a gateway context is still enforced. This is the middleware contract the lookup relies on; it is
    independent of how orders are fetched, so it is pinned on a hand-built event rather than one
    captured from a (now-removed) Lambda invoke."""
    from lambda_utils.middleware import require_auth
    internal_event = {
        'requestContext': {},  # no apiId -> internal Lambda-to-Lambda call
        'headers': {},         # no origin
        'rawPath': '/internal/orders',
        'queryStringParameters': {'email': 'customer@example.test'},
    }
    with patch('lambda_utils.middleware.cognito') as cognito:
        assert require_auth(internal_event) is None
        cognito.get_user.assert_not_called()
        gateway_event = {**internal_event,
                         'requestContext': {'apiId': 'gateway-test',
                                            'domainName': 'api.wecare.digital'}}
        response = require_auth(gateway_event)
        assert response['statusCode'] == 401
        cognito.get_user.assert_not_called()
