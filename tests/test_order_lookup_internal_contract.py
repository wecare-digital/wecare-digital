"""Order lookup must use IAM invocation context, never a browser Origin.

`fetch_orders_for_flow` reads OrdersTable and nothing else: the module's one AWS handle is a
DynamoDB resource, and every choice the picker offers comes back from an OrdersTable query.
The invocation-auth rule this file also guards is independent of where orders are read from:
an internal (IAM) invoke has no API Gateway `apiId` and is accepted; a call carrying a gateway
`apiId` is rejected 401. It is asserted directly against a synthetic internal event.
"""
import ast
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / 'amplify/functions/messaging/whatsapp-business-api/flows/orders.py'


def _load_orders():
    spec = importlib.util.spec_from_file_location('order_lookup_contract', ORDERS)
    orders = importlib.util.module_from_spec(spec)
    with patch('boto3.client'), patch('boto3.resource'):
        spec.loader.exec_module(orders)
    return orders


def test_the_lookup_module_holds_exactly_one_aws_handle():
    """A DynamoDB resource, and nothing it could invoke: OrdersTable is the one order source."""
    tree = ast.parse(ORDERS.read_text(encoding='utf-8'))
    factories = [(node.func.attr, node.args[0].value) for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'boto3']
    assert factories == [('resource', 'dynamodb')]


def test_flow_lookup_answers_from_the_orders_table_alone():
    """Every choice comes from an OrdersTable query on the `customerPhone` GSI."""
    orders = _load_orders()
    table = orders.dynamodb.Table.return_value
    table.query.return_value = {'Items': [
        {'orderId': 'order-1', 'orderNumber': 'WD-ORD-K4M7PQR9', 'createdAt': 1}]}
    choices = orders.fetch_orders_for_flow('+919876543210', 'customer@example.test')
    assert [choice['id'] for choice in choices] == ['order-1']
    assert {call.args[0] for call in orders.dynamodb.Table.call_args_list} == {orders.ORDERS_TABLE}
    assert table.query.call_args_list
    assert {call.kwargs['IndexName'] for call in table.query.call_args_list} == {'customerPhone'}


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
