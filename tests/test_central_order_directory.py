"""All order kinds share one customer directory, independent of CRM contact rows."""
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).parent))
from test_paid_submit_request import setup
from test_order_channel import _accept, CUSTOMER
from contribution_env import make_env, prepare_event, ATTEMPTS_TABLE
from contribution_wix import kiosk_line
from lambda_utils.ecommerce import order_keys
from lambda_utils.ecommerce import paid_submit_request as paid


def test_all_checkout_orders_keep_the_verified_whatsapp_number(monkeypatch):
    handler, fake, _ = make_env(monkeypatch)
    response=handler.handler(prepare_event([kiosk_line(1)]),None)
    assert response['statusCode']==200
    [attempt]=fake.all_rows(ATTEMPTS_TABLE)
    assert attempt['customerPhone'].startswith('+')
    order,_=_accept(customerPhone=attempt['customerPhone'])
    assert order['customerPhone']==attempt['customerPhone']
    assert order['customerId']==CUSTOMER


def test_selector_includes_all_product_and_service_order_types(setup):
    _, _, orders, paid_service=setup
    for number,kind in enumerate(['PRODUCT','DROP_DOCS','VAULT','REQUEST_AMENDMENT','SUBMIT_REQUEST']):
        # A distinct MINTABLE number per kind. 'WD-ORD-'+kind was never mintable: the minter emits
        # `WD-ORD-` plus exactly 8 characters of PUBLIC_ORDER_NUMBER_ALPHABET. The number is
        # incidental here - this test is about the selector covering every order KIND.
        orders.seed({'orderId':kind,'customerId':paid_service['customerId'],'createdAt':number+10,
                     'orderNumber':'WD-ORD-'+order_keys.PUBLIC_ORDER_NUMBER_ALPHABET[number]*8,
                     'kind':kind,'source':'wix'})
    selected={entry['id'] for entry in paid.list_orders(orders,paid_service)}
    assert {'PRODUCT','DROP_DOCS','VAULT','REQUEST_AMENDMENT','SUBMIT_REQUEST','earlier'}==selected
    assert paid_service['orderId'] not in selected
